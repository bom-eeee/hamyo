import discord
from discord.ext import commands
from LevelDataManager import LevelDataManager
from typing import Optional, Dict, Any, List
import logging
from datetime import datetime, timedelta
import json, os
import pytz

CONFIG_PATH = "config/level_config.json"
KST = pytz.timezone("Asia/Seoul")
GUILD_ID = [1378632284068122685, 1396829213100605580]
ROLE_IDS = {
        'hub': 1396829213172174890,
        'dado': 1396829213172174888,
        'daho': 1398926065111662703,
        'dakyung': 1396829213172174891
        }
    
def _load_levelcfg():
    if not os.path.exists(CONFIG_PATH):
        return {"guilds": {}}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def in_myinfo_allowed_channel():
    def check():
        async def predicate(ctx: commands.Context):
            # DM이나 길드 없는 곳에서는 막음
            if not ctx.guild:
                return False
            
            if ctx.guild.id not in GUILD_ID:
                return False

            # 관리자 무시
            if ctx.author.guild_permissions.administrator:
                return True

            cfg = _load_levelcfg()
            allowed = cfg.get("guilds", {}).get(str(ctx.guild.id), {}).get("my_info_channels", [])

            # 설정이 비어 있으면 전체 허용
            if not allowed:
                return True

            return ctx.channel.id in allowed
        return commands.check(predicate)
    return check()

class LevelCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_manager = LevelDataManager()
        self.logger = logging.getLogger(__name__)
        
        # 역할 정보
        self.role_info = {
            'hub': {'name': '허브', 'threshold': 0, 'emoji': '🌱'},
            'dado': {'name': '다도', 'threshold': 400, 'emoji': '🍃'},
            'daho': {'name': '다호', 'threshold': 1800, 'emoji': '🌸'},
            'dakyung': {'name': '다경', 'threshold': 6000, 'emoji': '🌟'}
        }
        
        self.role_order = ['hub', 'dado', 'daho', 'dakyung']
    
    async def cog_load(self):
        """Cog 로드 시 데이터베이스 초기화"""
        await self.data_manager.initialize_database()
        print(f"✅ {self.__class__.__name__} loaded successfully!")

    async def log(self, message):
        try:
            logger = self.bot.get_cog('Logger')
            if logger:
                await logger.log(message)
        except Exception as e:
            print(f"❌ {self.__class__.__name__} 로그 전송 중 오류 발생: {e}")
            
    def blossom_leaf(self, progress, milestones, *, mode="band", zero_leaf_for_zero=False):
        """
        progress: 현재 진행 수치 (정수 권장)
        milestones: 오름차순 마일스톤 리스트 (예: [4, 7] 또는 [5, 10, 20])
        mode:
        - "band"       : 일반 주간 항목(출석, 일지, 추천, 게시판, 상점)용
                            • 달성한 마일스톤 수만큼 🌸
                            • 다음 마일스톤까지의 '남은 칸' 중 현재 진행치만큼 🌿
                            • progress==0이면(=아무것도 안 했으면) 🌿도 표시하지 않음
        - "milestone"  : 음성활동 전용 (5/10/20 자리수 표현)
                            • 달성한 마일스톤 수만큼 🌸
                            • 남은 자릿수는 전부 🌿로 채움 (0일 때도 🌿 3개)
        zero_leaf_for_zero:
        - mode="band"에서만 의미 있음. True면 0일 때도 잎을 0개 대신 표시할 수 있게 확장 가능(기본 False).
        """

        if not milestones:
            return ""

        milestones = sorted(milestones)
        p = int(progress)

        # 달성한 마일스톤 개수
        blossoms = sum(1 for m in milestones if p >= m)

        if mode == "milestone":
            # 음성활동: 자리수 채우기 (항상 len(milestones) 길이의 아이콘)
            leaves = max(0, len(milestones) - blossoms)
            return " ".join(["🌸"] * blossoms + ["🌿"] * leaves)

        # mode == "band": 일반 주간 항목
        # 0이면(아무것도 안 했으면) 잎도 표시하지 않음
        if p <= 0 and not zero_leaf_for_zero:
            return " ".join(["🌸"] * blossoms)  # 보통은 ""가 됨

        # 다음 마일스톤 찾기 및 잎 계산
        prev_ms = 0
        next_ms = None
        for m in milestones:
            if p < m:
                next_ms = m
                break
            prev_ms = m

        leaves = 0
        if next_ms is not None:
            # 현재 구간에서 달성까지의 단위가 1씩 증가한다고 가정
            # 예) [4,7]에서 p=5 -> prev=4, next=7 -> leaves=1 (🌸 🌿)
            leaves = max(0, min(p - prev_ms, next_ms - prev_ms - 0))
        # 마지막 마일스톤을 넘은 경우 잎 0

        # 0에서 zero_leaf_for_zero=True인 경우를 제외하면 잎은 최소 0
        if p == 0 and not zero_leaf_for_zero:
            leaves = 0

        return " ".join(["🌸"] * blossoms + ["🌿"] * int(leaves))

    
    @commands.command(name='내정보', aliases=['myinfo', '정보'])
    @in_myinfo_allowed_channel()

    async def my_info(self, ctx):
        """내 경험치 및 퀘스트 정보 조회"""
        try:
            # ===== my_info 내용 시작: 여기부터 기존 임베드 구성 부분을 통째로 교체 =====
            member = ctx.author
            user_id = member.id

            # 0) 도우미 핸들/데이터 접근
            level_checker = ctx.bot.get_cog("LevelChecker")  # quest_exp, role_thresholds 참조
            data_manager = getattr(self, "data_manager", None) or getattr(level_checker, "data_manager", None)
            if data_manager is None or level_checker is None:
                return await ctx.reply("설정이 아직 준비되지 않았어요. 잠시 후 다시 시도해 주세요.")

            # 1) 기본 유저 데이터 (총 다공/현재 경지)
            user_data = await data_manager.get_user_exp(user_id) if hasattr(data_manager, "get_user_exp") else None
            total_exp = int(user_data.get("total_exp", 0)) if user_data else 0
            current_role_key = user_data.get("current_role", "hub") if user_data else "hub"

            # 2) 역할(경지) 임계값/진행률 계산 (LevelChecker.role_thresholds 기반)
            role_thresholds = getattr(level_checker, "role_thresholds", {"hub": 0, "dado": 400, "daho": 1800, "dakyung": 6000})
            role_order = getattr(level_checker, "role_order", ["hub", "dado", "daho", "dakyung"])
            role_display = getattr(level_checker, "ROLE_DISPLAY", {"hub": "허브", "dado": "다도", "daho": "다호", "dakyung": "다경"})

            role_obj = ctx.guild.get_role(ROLE_IDS[current_role_key])
            current_role_mention = role_obj.mention if role_obj else role_display.get(current_role_key, current_role_key)

            # 현재/다음 경지 경계 파악
            current_idx = role_order.index(current_role_key) if current_role_key in role_order else 0
            current_floor = role_thresholds.get(role_order[current_idx], 0)
            next_idx = min(current_idx + 1, len(role_order) - 1)
            next_key = role_order[next_idx]
            next_floor = role_thresholds.get(next_key, current_floor)

            # 최상위 경지면 진행률 100%로 고정
            if next_floor == current_floor:
                percent = 100
                need_to_next = 0
            else:
                gained_in_tier = max(0, total_exp - current_floor)
                tier_span = max(1, next_floor - current_floor)
                percent = int((gained_in_tier / tier_span) * 100)
                need_to_next = max(0, next_floor - total_exp)

            # 3) 인증 랭크(보이스/채팅) — 저장소에 없으면 0 처리
            voice_lv = 0
            chat_lv = 0
            if hasattr(data_manager, "get_all_certified_ranks"):
                try:
                    cert = await data_manager.get_all_certified_ranks(user_id)
                    voice_lv = int(cert.get("voice", 0))
                    chat_lv = int(cert.get("chat", 0))
                except Exception:
                    pass
            
            next_voice_lv = ((voice_lv // 5) + 1) * 5 if voice_lv % 5 != 0 else voice_lv + 5
            next_chat_lv = ((chat_lv // 5) + 1) * 5 if chat_lv % 5 != 0 else chat_lv + 5

            # 4) 일일/주간 집계 값 가져오기
            # 일일: 출석/일지/삐삐(카운트), 음성 분
            def _safe_get_quest(user, qtype, subtype, scope):
                if hasattr(data_manager, "get_quest_count"):
                    return data_manager.get_quest_count(user, qtype, subtype, scope)
                return None

            att_daily = await _safe_get_quest(user_id, 'daily', 'attendance', 'day') or 0
            diary_daily = await _safe_get_quest(user_id, 'daily', 'diary', 'day') or 0
            bb_daily = await _safe_get_quest(user_id, 'daily', 'bbibbi', 'day') or 0

            # DataManager의 일일/주간 음성 초 → 분/시간
            voice_sec_day = 0
            voice_sec_week = 0
            if hasattr(data_manager, "get_user_voice_seconds_daily"):
                voice_sec_day = await data_manager.get_user_voice_seconds_daily(user_id)
            if hasattr(data_manager, "get_user_voice_seconds_weekly"):
                voice_sec_week = await data_manager.get_user_voice_seconds_weekly(user_id)

            voice_min_daily = voice_sec_day // 60
            voice_min_week = voice_sec_week // 60
            voice_hour_week = voice_min_week // 60
            voice_rem_min_week = voice_min_week % 60

            # 주간: 출석/일지/추천/게시판/상점 카운트
            att_week = await _safe_get_quest(user_id, 'daily', 'attendance', 'week') or 0
            diary_week = await _safe_get_quest(user_id, 'daily', 'diary', 'week') or 0
            recommend_week = await _safe_get_quest(user_id, 'weekly', 'recommend', 'week') or 0
            board_week = await _safe_get_quest(user_id, 'weekly', 'board', 'week') or 0
            shop_week = await _safe_get_quest(user_id, 'weekly', 'shop_purchase', 'week') or 0

            # 5) 아이콘 유틸
            def ox(done: bool) -> str:
                return ":o:" if done else ":x:"

            # 6) 퀘스트 임계값 (LevelChecker.quest_exp의 정책과 예시를 반영)
            
            ATT_THRESH = (4, 7)
            DIARY_THRESH = (4, 7)
            RECO_THRESH = (3,)
            VOICE_THRESH = (5, 10, 20)
            SHOP_THRESH = (1,)
            BOARD_THRESH = (3,)

            # 7) 이번 주 총 획득 다공 및 순위
            weekly_total = await self.data_manager.get_user_period_exp(user_id, 'weekly')
            weekly_rank = await self.data_manager.get_user_period_rank(user_id, 'weekly')

            # 8) 임베드 구성
            embed = discord.Embed(
                title=f"🌙 、{member.display_name} 님의 수행⠀",
                color=await level_checker._get_role_color(current_role_key, ctx.guild) if hasattr(level_checker, "_get_role_color") else discord.Color.blue()
            )

            # 경지 진행 바 (5칸)
            bar_len = 5
            filled = min(bar_len, max(0, int(percent / (100 / bar_len))))
            bar = "▫️" * (bar_len - filled) + "◾️" * filled  # 예: ▫️▫️▫️◾️◾️

            embed.add_field(
                name="🪵◝. 경지 확인",
                value=(
                    f"⠀{bar}: {percent:02d}%\n"
                    f"> {current_role_mention} ( {total_exp:,} 다공 ) \n"
                    f"> -# ◟. 다음 경지까지 {need_to_next:,} 다공 필요"
                ),
                inline=False
            )

            # 인증된 랭크
            embed.add_field(
                name="📜◝. 퀘스트 현황\n\n˚‧ 📔: 인증된 랭크",
                value=(
                    f"> 음성 : {voice_lv} Lv  \n"
                    f"> 채팅 : {chat_lv} Lv \n"
                    f"> -# ◟. 다음 인증까지 보이스 {next_voice_lv - voice_lv} Lv / 채팅 {next_chat_lv - chat_lv} Lv "
                ),
                inline=False
            )

            # 일일 퀘스트
            embed.add_field(
                name="˚‧ 📆 : 일일 퀘스트",
                value=(
                    f"> 출석체크 : {ox(att_daily >= 1)} \n"
                    f"> 다방일지 : {ox(diary_daily >= 1)} \n"
                    f"> 다방삐삐 : {ox(bb_daily >= 1)}\n"
                    f"> 음성활동 : {voice_min_daily}분 / 30분 ({ox(voice_min_daily >= 30)})"
                ),
                inline=False
            )

            # 주간 퀘스트 (🌸/🌿)
            weekly_lines = []
            weekly_lines.append(f"> 출석체크 : {att_week} / 7 {self.blossom_leaf(att_week, ATT_THRESH)}")
            weekly_lines.append(f"> 비몽추천 : {recommend_week} / 3 {self.blossom_leaf(recommend_week, RECO_THRESH)}")
            weekly_lines.append(f"> 다방일지 : {diary_week} / 7 {self.blossom_leaf(diary_week, DIARY_THRESH)}")
            weekly_lines.append(f"> 음성활동 : {voice_hour_week}시간 {voice_rem_min_week}분 /  {self.blossom_leaf(voice_hour_week, VOICE_THRESH, mode="milestone")}")
            weekly_lines.append(f"> 상점구매 : {shop_week} / 1 {self.blossom_leaf(shop_week, SHOP_THRESH)}")
            weekly_lines.append(f"> 게시판이용 : {board_week} / 3 {self.blossom_leaf(board_week, BOARD_THRESH)}")

            embed.add_field(
                name="˚‧ 🗓️ : 주간 퀘스트",
                value="\n".join(weekly_lines) + f"\n\n이번 주 총 획득 : **{weekly_total:,} 다공** • 주간 **{weekly_rank}위** ",
                inline=False
            )

            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"요청자: {ctx.author}", icon_url=ctx.author.display_avatar.url)
            embed.timestamp = ctx.message.created_at

            await ctx.reply(embed=embed)
        except Exception as e:
            await ctx.reply("명령어 처리 중 오류가 발생했습니다. 관리자에게 문의해 주세요.")
            await self.log(f"{ctx.author}({ctx.author.id}) 님의 내정보 명령어 처리 중 오류 발생: {e}")
            return
    
    @commands.command(name='순위', aliases=['ranking', 'rank', 'leaderboard'])
    async def ranking(self, ctx, period: str = '누적'):
        """경험치 순위 조회"""
        valid_periods = ['일간', 'daily', '주간', 'weekly', '월간', 'monthly', '누적', 'total', 'all']
        
        if period not in valid_periods:
            embed = discord.Embed(
                title="❌ 잘못된 기간",
                description="사용 가능한 기간: `일간`, `주간`, `월간`, `누적`",
                color=0xff0000
            )
            await ctx.send(embed=embed)
            return
        
        # 기간 정규화
        if period in ['일간', 'daily']:
            period_type = 'daily'
            period_name = '일간'
            emoji = '📅'
        elif period in ['주간', 'weekly']:
            period_type = 'weekly'
            period_name = '주간'
            emoji = '📊'
        elif period in ['월간', 'monthly']:
            period_type = 'monthly'
            period_name = '월간'
            emoji = '📈'
        else:
            period_type = 'total'
            period_name = '누적'
            emoji = '🏆'
        
        # 순위 데이터 가져오기
        rankings = await self.data_manager.get_period_rankings(period_type)
        
        if not rankings:
            embed = discord.Embed(
                title=f"{emoji} {period_name} 순위",
                description="아직 순위 데이터가 없습니다.",
                color=0x999999
            )
            await ctx.send(embed=embed)
            return
        
        # 임베드 생성
        embed = discord.Embed(
            title=f"{emoji} {period_name} 경험치 순위",
            color=0xffd700
        )
        
        rank_emojis = ["🥇", "🥈", "🥉"] + ["🏅"] * 17
        
        # 사용자의 순위 찾기
        user_rank = None
        user_exp = None
        for i, (user_id, exp, role) in enumerate(rankings, 1):
            if user_id == ctx.author.id:
                user_rank = i
                user_exp = exp
                break
        
        # 상위 10명 표시
        leaderboard_text = ""
        for i, (user_id, exp, role) in enumerate(rankings[:10], 1):
            try:
                user = self.bot.get_user(user_id)
                username = user.display_name if user else f"Unknown User"
                role_emoji = self.role_info.get(role, {'emoji': '❓'})['emoji']
                role_name = self.role_info.get(role, {'name': role})['name']
                
                # 현재 사용자 강조
                if user_id == ctx.author.id:
                    leaderboard_text += f"{rank_emojis[i-1]} **{i}.** **{username}** ⭐\n"
                else:
                    leaderboard_text += f"{rank_emojis[i-1]} **{i}.** {username}\n"
                
                leaderboard_text += f"   └ {exp:,} 다공 ({role_emoji} {role_name})\n\n"
            except:
                continue
        
        embed.description = leaderboard_text
        
        # 사용자가 10위 밖이면 자신의 순위 표시
        if user_rank and user_rank > 10:
            embed.add_field(
                name="📍 내 순위",
                value=f"**{user_rank}위** - {ctx.author.display_name} ({user_exp:,} 다공)",
                inline=False
            )
        
        # 기간별 설명 추가
        if period_type != 'total':
            period_descriptions = {
                'daily': '오늘 획득한 경험치 기준',
                'weekly': '이번 주 획득한 경험치 기준',
                'monthly': '이번 달 획득한 경험치 기준'
            }
            embed.set_footer(text=period_descriptions[period_type])
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(LevelCommands(bot))
