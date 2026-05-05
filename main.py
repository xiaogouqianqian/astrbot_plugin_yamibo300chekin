import asyncio
import cloudscraper
from bs4 import BeautifulSoup
from lxml import html
from astrbot.api.all import *
from astrbot.api import AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, FunctionTool

@register("astrbot_plugin_yamibo", "YourName", "Yamibo 论坛自动签到插件", "1.1.0")
class YamiboCheckinPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        # 接收并保存配置对象
        self.config = config

    # 1. 保留传统的指令触发方式
    @filter.command("300签到") # type: ignore
    # 2. 增加 AI 工具触发方式，赋予大语言模型自动调用的能力
    @llm_tool(name="yamibo_auto_sign", desc="帮助用户在 300次元(Yamibo) 论坛进行自动打卡签到。当用户要求'签到300'、'打卡yamibo'或'签到论坛'时，请调用此工具。")
    async def yamibo_sign(self, event: AstrMessageEvent):
        """
        Yamibo 论坛签到。读取后台配置的 Cookie 进行签到。
        """
        # 从 WebUI 的配置项中读取 Cookie
        cookie = self.config.get("yamibo_cookie", "")
        
        if not cookie:
            yield event.plain_result("⚠️ 尚未配置 Cookie！\n请前往 AstrBot WebUI 管理面板 -> 插件配置中填写 `yamibo_cookie` 后再试。")
            return

        yield event.plain_result("⏳ 收到指令，正在为你前往 300次元 签到，请稍候...")
        
        # 将同步的爬虫任务放入线程池，防止阻塞机器人的主事件循环
        result_msg = await asyncio.to_thread(self._run_checkin_task, cookie)
        
        yield event.plain_result(f"【300 签到结果】\n{result_msg}")

    def _run_checkin_task(self, cookie: str) -> str:
        """后台运行的实际签到逻辑 (完全脱离主线程)"""
        msg = []
        
        headers = {
            "Host": "bbs.yamibo.com",
            "Connection": "keep-alive",
            "sec-ch-ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-full-version": "123.0.6312.106",
            "sec-ch-ua-arch": "x86",
            "sec-ch-ua-platform": "Windows",
            "sec-ch-ua-platform-version": "15.0.0",
            "sec-ch-ua-model": '""',
            "sec-ch-ua-bitness": "64",
            "sec-ch-ua-full-version-list": '"Google Chrome";v="123.0.6312.106", "Not:A-Brand";v="8.0.0.0", "Chromium";v="123.0.6312.106"',
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "Referer": "https://bbs.yamibo.com/plugin.php?id=zqlj_sign",
            "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8,ja;q=0.7,zh-TW;q=0.6",
            "Cookie": cookie,
        }

        # 使用 cloudscraper 绕过可能存在的 Cloudflare 验证
        session = cloudscraper.create_scraper()
        session.headers.update(headers)

        def fhash():
            url = "https://bbs.yamibo.com/plugin.php?id=zqlj_sign"
            try:
                r = session.get(url, timeout=15)
                tree = html.fromstring(r.text)
                hash_val = tree.xpath('//*[@id="scbar_form"]/input[2]')[0].attrib['value']
                return hash_val
            except Exception as e:
                msg.append({"name": "获取 form fhash 失败", "value": str(e)})
                return ""

        def check_in():
            code = fhash()
            if not code:
                return False

            url = "https://bbs.yamibo.com/plugin.php?id=zqlj_sign&sign=" + code
            try:
                r = session.get(url, timeout=15)
                tree = html.fromstring(r.text)
                message = tree.xpath('//*[@id="messagetext"]/p[1]/text()')[0]
                
                if "打卡成功" in message:
                    msg.append({"name": "签到信息", "value": "签到成功"})
                elif "打过卡" in message:
                    msg.append({"name": "签到信息", "value": "已签到"})
                elif "登录" in message:
                    msg.append({"name": "签到信息", "value": "登录失败，Cookie 可能已失效"})
                    return False
                else:
                    msg.append({"name": "签到信息", "value": message})
                    return False
                return True
            except Exception as e:
                msg.append({"name": "签到错误", "value": str(e)})
                return False

        def query_credit():
            try:
                # 抓取用户统计信息
                r = session.get("https://bbs.yamibo.com/plugin.php?id=zqlj_sign", timeout=15)
                tree = html.fromstring(r.text)
                stat = tree.xpath('//*[@id="wp"]/div[2]/div[2]/div[3]/div[2]/ul/li/text()')
                msg.extend([{"name": s.split("：")[0], "value": s.split("：")[1]} for s in stat if "：" in s])
            except Exception as e:
                msg.append({"name": "查询对象失败", "value": str(e)})

            try:
                # 抓取积分明细
                r = session.get("https://bbs.yamibo.com/home.php?mod=spacecp&ac=credit", timeout=15)
                soup = BeautifulSoup(r.text, "lxml")
                tree = html.fromstring(str(soup))
                credit = tree.xpath('//ul[@class="creditl mtm bbda cl"]/li/text()')
                data = [i.strip() for i in credit if i.strip()]
                
                if len(data) >= 4:
                    msg.extend([
                        {"name": "对象", "value": data[1]},
                        {"name": "积分", "value": data[2]},
                        {"name": "总积分", "value": data[3]},
                        {"name": "规则", "value": "总积分 = 积分 + 对象/3"}
                    ])
            except Exception as e:
                msg.append({"name": "查询积分失败", "value": str(e)})

        # 核心执行流程
        if check_in():
            query_credit()
            
        if not msg:
            return "未能获取任何签到信息，请检查网络或 Cookie 是否正确。"

        # 将 msg 列表格式化为文本返回
        return "\n".join([f"{one.get('name')}: {one.get('value')}" for one in msg])