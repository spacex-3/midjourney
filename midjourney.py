import json
import requests
import base64
import os
import traceback
import re
import sys
import atexit

from datetime import datetime, timedelta
from typing import Tuple
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

from plugins import register, Plugin, Event, Reply, ReplyType, logger
from channel.wrest import WrestChannel
from .ctext import *
from .expired_dict import ExpiredDict




@register
class Midjourney(Plugin):
    name = "midjourney"
    
    def __init__(self, config):
        super().__init__(config)
        self.trigger_prefix = "$"
        
        try:
            #默认配置
            gconf = {
                "mj_admin_password": "12345678",
                "daily_limit": 10
            }

            # 配置文件路径
            curdir = os.path.dirname(__file__)
            self.roll_path = os.path.join(curdir, "user_info.pkl")
            self.user_datas_path = os.path.join(curdir, "user_datas.pkl")
            self.json_path = os.path.join(curdir, "config.json")
            tm_path = os.path.join(curdir, "config.json.template")

            # 读取配置文件
            self.commands = self.config.get("command", [])
            self.proxy_server = self.config.get("proxy_server")
            self.proxy_api_secret = self.config.get("proxy_api_secret")
            self.openai_api_base = self.config.get("openai_api_base")
            self.openai_api_key = self.config.get("openai_api_key")

            jld = {}
            if os.path.exists(self.json_path):
                jld = json.loads(read_file(self.json_path))
            elif os.path.exists(tm_path):
                jld = json.loads(read_file(tm_path))

            self.nconfig = {**gconf, **jld}

            self.mj_admin_password = self.nconfig.get("mj_admin_password")
            self.daily_limit = self.nconfig.get("daily_limit")
            
            self.task_id_dict = ExpiredDict(60 * 60)
            self.cmd_dict = ExpiredDict(60 * 60)

            # 创建调度器（使用 BackgroundScheduler 而不是 BlockingScheduler）
            self.jobstores = {
                'default': MemoryJobStore(),  # 使用内存存储任务
            }

            # 线程池执行器，允许更多的并发任务
            self.executors = {
                'default': ThreadPoolExecutor(10),  # 设置线程池大小
            }

            self.scheduler = BackgroundScheduler(jobstores=self.jobstores, executors=self.executors)

            # 添加任务，设置 max_instances 为 5，允许并发执行最多 5 个任务
            self.scheduler.add_job(self.query_task_result, 'interval', seconds=10, max_instances=5)
            
            # 启动调度器
            self.scheduler.start()

            # 注册程序退出时的清理函数，确保调度器能够优雅关闭
            atexit.register(self.graceful_shutdown)

            # 重新写入合并后的配置文件
            write_file(self.json_path, self.nconfig)

            # 初始化用户数据
            self.roll = {
                "mj_admin_users": [],
                "mj_groups": [],
                "mj_users": [],
                "mj_bgroups": [],
                "mj_busers": []
            }
            if os.path.exists(self.roll_path):
                sroll = read_pickle(self.roll_path)
                self.roll = {**self.roll, **sroll}

            # 写入用户列表
            write_pickle(self.roll_path, self.roll)

            # 初始化用户数据
            self.user_datas = {}
            if os.path.exists(self.user_datas_path):
                self.user_datas = read_pickle(self.user_datas_path)
                logger.debug(f"[MJ] Loaded user_datas: {self.user_datas}")
            else:
                now = datetime.now()
                # 初始化用户数据结构
                self.user_datas['uid'] = {
                    'mj_datas': {
                        'nickname': '默认昵称',
                        'isgroup': False,
                        'group_name': '非群聊',
                        'default_limit': self.daily_limit,
                        'limit': self.daily_limit,
                        'expire_time': now + timedelta(days=30),  # 30 天后过期
                        'update_time': now  # 初始化 update_time
                    }
            }
                                
            self.ismj = True  # 机器人是否运行中

            logger.debug("[MJ] inited")

        except Exception as e:
            logger.debug(f"[MJ] init failed, ignored.")
            logger.warning(f"Traceback: {traceback.format_exc()}")
            raise e

    # 优雅关闭调度器的函数
    def graceful_shutdown(self):
        logger.debug("正在优雅关闭调度器...")
        self.scheduler.shutdown(wait=False)  # 关闭调度器
        logger.debug("调度器已关闭")
        sys.exit(0)  # 正常退出程序
    

    def help(self, **kwargs) -> str:

        # 生成普通用户的帮助文本
        help_text = f"这是一个能调用midjourney实现ai绘图的扩展能力。\n使用说明:\n/imagine 根据给出的提示词绘画;\n/img2img 根据提示词+垫图生成图;\n/up 任务ID 序号执行动作;\n/describe 图片转文字;\n/shorten 提示词分析;\n/seed 获取任务图片的seed值;\n\n注意，使用本插件请避免政治、色情、名人等相关提示词，监测到则可能存在停止使用风险。"

        # 如果是管理员，附加管理员指令的帮助信息
        if kwargs.get("admin", False) is True:
            help_text += "\n\n管理员指令：\n"
            for cmd, info in ADMIN_COMMANDS.items():
                alias = [self.trigger_prefix + a for a in info["alias"][:1]]
                help_text += f"{','.join(alias)} "
                if "args" in info:
                    args = [a for a in info["args"]]
                    help_text += f"{' '.join(args)}"
                help_text += f": {info['desc']}\n"

        return help_text

    def generate_trans_prompt(self, content):
        # GPT的翻译文本
        trans_prompt = f"""我希望你仅充当 Midjourney V6英文提示词的翻译，无论我给你什么语言的提示，全部直接翻译成中文，且仅返回翻译好的内容，不要有任何其他分析过程。"""
        try:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.openai_api_key}'
            }
            data = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": trans_prompt},
                    {"role": "user", "content": content}
                ]
            }
            api_url = f"{self.openai_api_base}/chat/completions"

            # 记录发送给OpenAI的请求内容
            logger.debug(f"optimized_prompt: 发送的请求URL: {api_url}")
            logger.debug(f"optimized_prompt: 发送的请求头: {headers}")
            logger.debug(f"optimized_prompt: 发送的请求数据: {json.dumps(data, indent=2, ensure_ascii=False)}")

            response = requests.post(api_url, headers=headers, data=json.dumps(data))
            response.raise_for_status()
            response_data = response.json()
            
            if "choices" in response_data and len(response_data["choices"]) > 0:
                first_choice = response_data["choices"][0]
                if "message" in first_choice and "content" in first_choice["message"]:
                    response_content = first_choice["message"]["content"].strip()  # 获取响应内容

                    logger.debug(f"翻译后提示词如下：{response_content}")  # 记录响应内容

                    trans_prompt = response_content.replace("\\n", "\n")  # 替换 \\n 为 \n

                    return trans_prompt
                else:
                    logger.debug("Content not found in the response")
                    return content
            else:
                logger.debug(f"Optimized prompt from GPT: {trans_prompt}")
                return trans_prompt

        except Exception as e:
            logger.debug(f"Error while calling GPT API: {e}")
            return content  # 如果出现错误，返回原始内容


    def generate_optimized_prompt(self, event: Event):
        
        # GPT的提示文本，要求其优化提示词并添加画布比例和风格
        gpt_prompt = f"""我希望你充当 Midjourney V6人工智能画图程序的提示生成器.\n请注意永远永远永远只按照这个格式的内容返回“🆎 English：具体提示词本身内容英文原文（需包括画布比例和图像风格）\n\n🀄️ 中文：具体提示词本身内容的中文翻译（需包括画布比例和图像风格）”，不要有任何其他分析过程，也不用"/imagine "作为开头，以便我直接复制给MJ!\n你的具体工作是在不脱离我给你的提示词内容的前提下，提供详细而富有创意的描述，以激发AI创造独特且有趣的图像。请记住，AI有能力理解广泛的语言并能解释抽象概念，因此尽管自由发挥你的想象力和描述能力。你的描述越详细和富有想象力，结果图像就会越有趣。\n记得提示词最后要按照MJ官方格式（如"--ar 16:9"）补充画布比例和图像风格（如"--v 6"或者"--niji"），画布比例和图像风格如果我给你的提示词没有明确要求，则你自己根据我给你的提示判断画布比例是1:1还是16:9还是9:16或者其他比例最适合，风格同理。若我给你的提示明确表示不需要润色和丰富只需要直接翻译，则仅翻译为英文即可。"""
        channel = WrestChannel()
        try:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.openai_api_key}'
            }
            data = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": gpt_prompt},
                    {"role": "user", "content": event.message.content}
                ]
            }
            api_url = f"{self.openai_api_base}/chat/completions"

            # 记录发送给OpenAI的请求内容
            logger.debug(f"optimized_prompt: 发送的请求URL: {api_url}")
            logger.debug(f"optimized_prompt: 发送的请求头: {headers}")
            logger.debug(f"optimized_prompt: 发送的请求数据: {json.dumps(data, indent=2, ensure_ascii=False)}")

            response = requests.post(api_url, headers=headers, data=json.dumps(data))
            response.raise_for_status()
            response_data = response.json()
            
            if "choices" in response_data and len(response_data["choices"]) > 0:
                first_choice = response_data["choices"][0]
                if "message" in first_choice and "content" in first_choice["message"]:
                    response_content = first_choice["message"]["content"].strip()  # 获取响应内容

                    logger.debug(f"优化后提示词如下：{response_content}")  # 记录响应内容

                    optimized_prompt = response_content.replace("\\n", "\n")  # 替换 \\n 为 \n

                    # 判断是群聊还是私聊，并设置目标 ID
                    target_id = event.message.room_id if event.message.is_group else event.message.sender_id

                    # 发送消息到目标 ID
                    channel.send_txt(
                        f"💡 提示词已优化，可作为参考\n\n{optimized_prompt} \n\n⏳ 任务正在提交，请稍后",
                        target_id
                    )

                    return optimized_prompt
                else:
                    logger.debug("Content not found in the response")
                    return event.message.content
            else:
                logger.debug(f"Optimized prompt from GPT: {optimized_prompt}")
                return optimized_prompt

        except Exception as e:
            logger.debug(f"Error while calling GPT API: {e}")
            return event.message.content  # 如果出现错误，返回原始内容

    def will_decorate_reply(self, event: Event):
        pass

    def will_send_reply(self, event: Event):
        pass

    def will_generate_reply(self, event: Event):
        pass

    def did_receive_message(self, event: Event):
        
        query = event.message.content.strip()
        is_group = event.message.is_group
        is_at = event.message.is_at

        if event.message.type not in [1]:
            return

        # 如果是群聊，且消息没有 @机器人，则直接返回
        if is_group:  # and not is_at:
            return

        # 如果是群聊，移除 @机器人 的内容
        #if is_group and is_at:
        #   query = re.sub(r'@[\w]+\s+', '', query, count=1).strip()
        
        try:
            if not isinstance(self.user_datas, dict):
                logger.debug(f"Expected self.user_datas to be a dictionary, but got {type(self.user_datas)}")

            context = event.message
            content = query
            msg = event.message
            # 创建一个回复对象
            reply = Reply(ReplyType.TEXT, "")
            logger.debug(f"[MJ] did_receive_message. content={content}")            

            if context.type == 1 and content.startswith(self.trigger_prefix):
                
                self.userInfo = self.get_user_info(event)
                if not isinstance(self.userInfo, dict):
                    logger.debug(f"Expected self.userInfo to be a dictionary, but got {type(self.userInfo)}")
                    logger.debug(f"[MJ] userInfo: {self.userInfo}")
                self.isgroup = self.userInfo["isgroup"]
                
                # 拦截非白名单黑名单群组
                if not self.userInfo["isadmin"] and self.isgroup and not self.userInfo["iswgroup"] and self.userInfo["isbgroup"]:
                    logger.debug("[MJ] Blocked by group blacklist.")
                    return

                # 拦截黑名单用户
                if not self.userInfo["isadmin"] and self.userInfo["isbuser"]:
                    logger.debug("[MJ] Blocked by user blacklist.")
                    return
                
                else:
                    return self.handle_command(event)

            # 判断 sender_id 是群聊的 room_id 还是私聊的 sender_id
            sender_id = msg.room_id if msg.is_group else msg.sender_id

            # 根据 sender_id 和 sender_name 构造 state
            state = f"u:{sender_id}:{msg.sender_name}"

            result = None

            try:
                if content.startswith("/imagine ") or content.startswith(tuple(self.commands)): #“画”字取代dalle3，所以dalle3设置成“画画”
                    
                    # 判断是否在运行中
                    if not self.ismj:
                        reply = Reply(ReplyType.TEXT, "MJ功能已停止，请联系管理员开启。")
                        event.channel.send(reply, event.message)
                        event.bypass()  
                        return                   
                    #前缀开头匹配才记录用户信息以免太多不相关的用户被记录
                    self.userInfo = self.get_user_info(event)
                    if not isinstance(self.userInfo, dict):
                        logger.debug(f"Expected self.userInfo to be a dictionary, but got {type(self.userInfo)}")
                        logger.debug(f"[MJ] userInfo: {self.userInfo}")
                    
                    self.isgroup = self.userInfo["isgroup"]

                    #用户资格判断
                    env = env_detection(self, event)
                    if not env:
                        return
                    
                    reply = Reply(ReplyType.TEXT, "✅ 已收到您的提示词，正在由GPT4润色，请稍后。")
                    event.channel.send(reply, event.message)

                    # 提取用户输入的提示词部分
                    user_prompt = content[1:].strip()

                    # 调用GPT润色中英文提示词
                    optimized_prompt = self.generate_optimized_prompt(event, user_prompt)
                    logger.debug(f"[{optimized_prompt}")

                    # 提取纯英文部分    
                    match = re.search(r"🆎 English：(.*?)🀄️", optimized_prompt, re.DOTALL) 
                    if match:
                        english_prompt = match.group(1).replace("\n", " ")  # 去掉换行符
                        logger.debug(f"[已找到英文提示词：{english_prompt}")
                    else:
                        english_prompt = optimized_prompt
                        logger.debug(f"[没有英文提示词，直接发送完整提示词：{english_prompt}")

                    # 将优化后的提示词传递给handle_imagine处理
                    result = self.handle_imagine(english_prompt, state)

                elif content.startswith("/up "):

                    # 判断是否在运行中
                    if not self.ismj:
                        reply = Reply(ReplyType.TEXT, "MJ功能已停止，请联系管理员开启。")
                        event.channel.send(reply, event.message)
                        event.bypass()  
                        return                          
                    #前缀开头匹配才记录用户信息以免太多不相关的用户被记录
                    self.userInfo = self.get_user_info(event)
                    if not isinstance(self.userInfo, dict):
                        logger.debug(f"Expected self.userInfo to be a dictionary, but got {type(self.userInfo)}")
                    logger.debug(f"[MJ] userInfo: {self.userInfo}")
                    self.isgroup = self.userInfo["isgroup"]

                    #用户资格判断
                    env = env_detection(self, event.message)
                    if not env:
                        return                    
                    
                    arr = content[4:].split()
                    try:
                        task_id = arr[0]
                        index = int(arr[1])
                    except Exception as e:
                        reply = Reply(ReplyType.TEXT, "❌ 您的任务提交失败\nℹ️ 参数错误")
                        event.channel.send(reply, event.message)
                        event.bypass()  
                        return
                    # 获取任务
                    task = self.get_task(task_id)
                    if task is None:
                        reply = Reply(ReplyType.TEXT, "❌ 您的任务提交失败\nℹ️ 任务ID不存在")
                        event.channel.send(reply, event.message)
                        event.bypass()                          
                        return
                    if index > len(task['buttons']):
                        reply = Reply(ReplyType.TEXT, "❌ 您的任务提交失败\nℹ️ 按钮序号不正确")
                        event.channel.send(reply, event.message)
                        event.bypass()                          
                        return
                    # 获取按钮
                    button = task['buttons'][index - 1]
                    if button['label'] == 'Custom Zoom':
                        reply = Reply(ReplyType.TEXT, "❌ 您的任务提交失败\nℹ️ 暂不支持自定义变焦")
                        event.channel.send(reply, event.message)
                        event.bypass()                          
                        return
                    result = self.post_json('/submit/action',
                                            {'customId': button['customId'], 'taskId': task_id, 'state': state})
                    if result.get("code") == 21:
                        result = self.post_json('/submit/modal',
                                            {'taskId': result.get("result"), 'state': state})
                elif content.startswith("/img2img "):
                    # 判断是否在运行中
                    if not self.ismj:
                        reply = Reply(ReplyType.TEXT, "MJ功能已停止，请联系管理员开启。")
                        event.channel.send(reply, event.message)
                        event.bypass()                                               
                        return                          
                    #前缀开头匹配才记录用户信息以免太多不相关的用户被记录
                    self.userInfo = self.get_user_info(event)
                    if not isinstance(self.userInfo, dict):
                        logger.debug(f"Expected self.userInfo to be a dictionary, but got {type(self.userInfo)}")
                    logger.debug(f"[MJ] userInfo: {self.userInfo}")
                    self.isgroup = self.userInfo["isgroup"]

                    #用户资格判断
                    env = env_detection(self, event)
                    if not env:
                        return                    
                    
                    self.cmd_dict[msg.sender_id] = content

                    reply = Reply(ReplyType.TEXT, "请给我发一张图片作为垫图")
                    event.channel.send(reply, event.message)
                    event.bypass()                  
                    return
                elif content == "/describe":
                    # 判断是否在运行中
                    if not self.ismj:
                        reply = Reply(ReplyType.TEXT, "MJ功能已停止，请联系管理员开启。")
                        event.channel.send(reply, event.message)
                        event.bypass()                                              
                        return      
                    #前缀开头匹配才记录用户信息以免太多不相关的用户被记录
                    self.userInfo = self.get_user_info(event)
                    if not isinstance(self.userInfo, dict):
                        logger.debug(f"Expected self.userInfo to be a dictionary, but got {type(self.userInfo)}")
                    logger.debug(f"[MJ] userInfo: {self.userInfo}")
                    self.isgroup = self.userInfo["isgroup"]

                    #用户资格判断
                    env = env_detection(self, event)
                    if not env:
                        return        

                    self.cmd_dict[msg.actual_user_id] = content
                    reply = Reply(ReplyType.TEXT, "请给我发一张图片用于图生文")
                    event.channel.send(reply, event.message)
                    event.bypass()                      
                    return
                elif content.startswith("/shorten "):
                    # 判断是否在运行中
                    if not self.ismj:
                        reply = Reply(ReplyType.TEXT, "MJ功能已停止，请联系管理员开启。")
                        event.channel.send(reply, event.message)
                        event.bypass()                                               
                        return      
                    #前缀开头匹配才记录用户信息以免太多不相关的用户被记录
                    self.userInfo = self.get_user_info(event)
                    if not isinstance(self.userInfo, dict):
                        logger.debug(f"Expected self.userInfo to be a dictionary, but got {type(self.userInfo)}")
                    logger.debug(f"[MJ] userInfo: {self.userInfo}")
                    self.isgroup = self.userInfo["isgroup"]

                    #用户资格判断
                    env = env_detection(self, event)
                    if not env:
                        return        

                    result = self.handle_shorten(content[9:], state)
                elif content.startswith("/seed "):
                    # 判断是否在运行中
                    if not self.ismj:
                        reply = Reply(ReplyType.TEXT, "MJ功能已停止，请联系管理员开启。")
                        event.channel.send(reply, event.message)
                        event.bypass()                                               
                        return      
                    #前缀开头匹配才记录用户信息以免太多不相关的用户被记录
                    self.userInfo = self.get_user_info(event)
                    if not isinstance(self.userInfo, dict):
                        logger.debug(f"Expected self.userInfo to be a dictionary, but got {type(self.userInfo)}")
                    logger.debug(f"[MJ] userInfo: {self.userInfo}")
                    self.isgroup = self.userInfo["isgroup"]
                    
                    #用户资格判断
                    env = env_detection(self, event)
                    if not env:
                        return        

                    task_id = content[6:]
                    result = self.get_task_image_seed(task_id)
                    if result.get("code") == 1:
                        event.channel.send(Reply(ReplyType.TEXT, f'✅ 获取任务图片seed成功\n📨 任务ID: %s\n🔖 seed值: %s' % (
                                        task_id, result.get("result"))), event.message)
                    else:
                        event.channel.send(Reply(ReplyType.TEXT, f'❌ 获取任务图片seed失败\n📨 任务ID: %s\nℹ️ %s' % (
                                        task_id, result.get("description"))), event.message)
                    event.bypass() 
                    return
                elif context.type == 3:
                    cmd = self.cmd_dict.get(msg.actual_user_id)
                    if not cmd:
                        return
                    msg.prepare()
                    self.cmd_dict.pop(msg.actual_user_id)
                    if "/describe" == cmd:
                        result = self.handle_describe(content, state)
                    elif cmd.startswith("/img2img "):
                        result = self.handle_img2img(content, cmd[9:], state)
                    else:
                        return
                else:
                    return
            except Exception as e:
                logger.exception("[MJ] handle failed: %s" % e)
                result = {'code': -9, 'description': '服务异常, 请稍后再试'}
            code = result.get("code")
            # 获取用户当前剩余次数和有效期
            uid_group = f"{self.userInfo['user_id']}_{self.userInfo['group_name'] if self.userInfo['isgroup'] else '非群聊'}"
            remaining_uses = self.user_datas[uid_group]["mj_datas"]["limit"]
            user_expire_time = self.user_datas[uid_group]["mj_datas"]["expire_time"]

            if code == 1:
                task_id = result.get("result")
                self.add_task(task_id)
                reply = Reply(ReplyType.TEXT, f'✅ 您的任务已提交\n🚀 正在快速处理中，请稍后\n📨 任务ID: {task_id} \n⏳本次生成图像后，有效期内还剩余 {remaining_uses - 1} 次\n⏰有效期: {user_expire_time}')
                event.channel.send(reply, event.message)
            elif code == 22:
                self.add_task(result.get("result"))
                reply = Reply(ReplyType.TEXT, f'✅ 您的任务已提交\n⏰ {result.get("description")} \n⏳本次生成图像后，有效期内还剩余 {remaining_uses - 1} 次\n⏰有效期: {user_expire_time}')
                event.channel.send(reply, event.message)
            else:
                reply = Reply(ReplyType.TEXT, f'❌ 您的任务提交失败\nℹ️ {result.get("description")} \n⏳本次不扣除次数，有效期内还剩余 {remaining_uses} 次\n⏰有效期: {user_expire_time}')
                event.channel.send(reply, event.message)
            event.bypass() 
        except Exception as e:
            logger.warning(f"[MJ] failed to generate pic, error={e}")
            logger.warning(f"Traceback: {traceback.format_exc()}")
            reply = Reply(ReplyType.TEXT, "抱歉！创作失败了，请稍后再试🥺")
            event.channel.send(reply, event.message)
            event.bypass() 


    def handle_imagine(self, prompt, state):
        return self.post_json('/submit/imagine', {'prompt': prompt, 'state': state})

    def handle_describe(self, img_data, state):
        base64_str = self.image_file_to_base64(img_data)
        return self.post_json('/submit/describe', {'base64': base64_str, 'state': state})

    def handle_shorten(self, prompt, state):
        return self.post_json('/submit/shorten', {'prompt': prompt, 'state': state})

    def handle_img2img(self, img_data, prompt, state):
        base64_str = self.image_file_to_base64(img_data)
        return self.post_json('/submit/imagine', {'prompt': prompt, 'base64': base64_str, 'state': state})

    def post_json(self, api_path, data):
        return requests.post(url=self.proxy_server + api_path, json=data,
                             headers={'mj-api-secret': self.proxy_api_secret}).json()

    def get_task(self, task_id):
        return requests.get(url=self.proxy_server + '/task/%s/fetch' % task_id,
                            headers={'mj-api-secret': self.proxy_api_secret}).json()
    
    def get_task_image_seed(self, task_id):
        return requests.get(url=self.proxy_server + '/task/%s/image-seed' % task_id,
                        headers={'mj-api-secret': self.proxy_api_secret}).json()

    def add_task(self, task_id):
        self.task_id_dict[task_id] = 'NOT_START'

    def query_task_result(self):
        channel = WrestChannel()
        task_ids = list(self.task_id_dict.keys())
        if len(task_ids) == 0:
            return
        logger.debug("[MJ] handle task , size [%s]", len(task_ids))
        tasks = self.post_json('/task/list-by-condition', {'ids': task_ids})
        for task in tasks:
            task_id = task['id']
            description = task['description']
            status = task['status']
            action = task['action']
            state_array = task['state'].split(':', 2)

            # Check length of state_array
            if len(state_array) >= 3:
                context = state_array[1] #获取state里面的 sender_id
                reply_prefix = '@%s ' % state_array[2] if state_array[0] == 'r' else ''
            else:
                logger.debug(f"Invalid state format: {task['state']}")
                continue  # Skip this task or handle the error appropriately

            if status == 'SUCCESS':
                logger.debug("[MJ] 任务已完成: " + task_id)
                self.task_id_dict.pop(task_id)

                if action == 'DESCRIBE' or action == 'SHORTEN':
                    prompt = task['properties']['finalPrompt']
                    channel.send_txt((reply_prefix + '✅ 任务已完成\n📨 任务ID: %s\n%s\n\n' + self.get_buttons(
                            task) + '\n' + '💡 使用 /up 任务ID 序号执行动作\n🔖 /up %s 1') % (
                                      task_id, prompt, task_id), context)
                    
                elif action == 'UPSCALE':
                    channel.send_txt(('✅ 任务已完成\n📨 任务ID: %s\n✨ %s\n\n' + self.get_buttons(
                                      task) + '\n' + '💡 使用 /up 任务ID 序号执行动作\n🔖 /up %s 1') % (
                                      task_id, description, task_id), context)
                    channel.send_img(task['imageUrl'], context)

                    # 成功生成图像后调用
                    self.update_limit(self.userInfo['user_id'], self.userInfo['group_name'], 1)
                    write_pickle(self.user_datas_path, self.user_datas)

                else:
                    channel.send_txt(('✅ 任务已完成\n📨 任务ID: %s\n✨ %s\n\n' + self.get_buttons(
                                      task) + '\n' + '💡 使用 /up 任务ID 序号执行动作\n🔖 /up %s 1') % (
                                      task_id, description, task_id), context)
                    channel.send_img(task['imageUrl'], context)

                    # 成功生成图像后调用更新次数
                    self.update_limit(self.userInfo['user_id'], self.userInfo['group_name'], 1)
                    write_pickle(self.user_datas_path, self.user_datas)

            elif status == 'FAILURE':
                self.task_id_dict.pop(task_id)
                channel.send_txt(reply_prefix + '❌ 任务执行失败，请重试\n✨ %s\n📨 任务ID: %s\n📒 失败原因: %s' % (
                              description, task_id, task['failReason']), context)

    def image_file_to_base64(self, file_path):
        with open(file_path, "rb") as image_file:
            img_data = image_file.read()
        img_base64 = base64.b64encode(img_data).decode("utf-8")
        os.remove(file_path)
        return "data:image/png;base64," + img_base64

    def get_buttons(self, task):
        # 定义 emoji 和 label 的字典
        emoji_dict = {
            "upscale_1": "🔼",
            "🪄": "✨",
            "🖌️": "🎨",
            "🔍": "🔍",
            "⬅️": "⬅️",
            "➡️": "➡️",
            "⬆️": "⬆️",
            "⬇️": "⬇️",
            "🔄": "🔄",  # 重新生成
        }

        label_dict = {
            "Upscale (Subtle)": "提升质量（微妙）",
            "Upscale (Creative)": "提升质量（创意）",
            "Redo Upscale (Subtle)": "重做提升质量（微妙）",
            "Redo Upscale (Creative)": "重做提升质量（创意）",
            "Vary (Subtle)": "变化（微妙）",
            "Vary (Strong)": "变化（强烈）",
            "Vary (Region)": " ", #变化（区域）不支持
            "Zoom Out 2x": "缩小 2 倍",
            "Zoom Out 1.5x": "缩小 1.5 倍",
            "Custom Zoom": " ", #自定义缩放 不支持
            "Make Square": "生成方形",
            "⬅️": "向左偏移",
            "➡️": "向右偏移",
            "⬆️": "向上偏移",
            "⬇️": "向下偏移",
            "U1": "🔍 放大图片1",
            "U2": "🔍 放大图片2",
            "U3": "🔍 放大图片3",
            "U4": "🔍 放大图片4",
            "V1": "🪄 延伸图片1",
            "V2": "🪄 延伸图片2",
            "V3": "🪄 延伸图片3",
            "V4": "🪄 延伸图片4",
            "🔄": " 重新生成",
            "": "",  # 对于空字符串，不进行翻译
        }

        res = ''
        index = 1
        for button in task['buttons']:
            # 获取原始 emoji 和 label
            emoji = button.get('emoji', '')
            label = button.get('label', '')

            # 使用字典更新 emoji 和 label
            updated_emoji = emoji_dict.get(emoji, emoji)  # 如果字典中没有找到对应的 emoji，则使用原始值
            updated_label = label_dict.get(label if label else emoji, label_dict.get(emoji, label))  # 通过 emoji 查找自定义 label

            # 拼接 emoji 和 label
            name = updated_emoji + updated_label

            # 跳过某些特定的按钮
            if name in ['🎉Imagine all', '❤️']:
                continue

            # 构建返回字符串
            res += ' %d- %s\n' % (index, name)
            index += 1

        return res

    # 指令处理
    def handle_command(self, event: Event):
        content = event.message.content
        com = content[1:].strip().split()
        cmd = com[0]
        args = com[1:]
        if any(cmd in info["alias"] for info in COMMANDS.values()):
            cmd = next(c for c, info in COMMANDS.items() if cmd in info["alias"])
            if cmd == "mj_help":
                event.channel.send(Reply(ReplyType.TEXT, self.help), event.message)
                event.bypass()
            elif cmd == "mj_admin_cmd":
                if not self.userInfo["isadmin"]:
                     event.channel.send(Reply(ReplyType.TEXT, "[MJ] 您没有权限执行该操作，请先进行管理员认证"), event.message)
                     event.bypass()
                event.channel.send(Reply(ReplyType.TEXT, self.get_help_text(admin=True)), event.message)
                event.bypass()
            elif cmd == "mj_admin_password":
                ok, result = self.authenticate(self.userInfo, args)
                if not ok:
                    event.channel.send(Reply(ReplyType.TEXT, result), event.message)
                    event.bypass()
                else:
                    event.channel.send(Reply(ReplyType.TEXT, result), event.message)
                    event.bypass()
        elif any(cmd in info["alias"] for info in ADMIN_COMMANDS.values()):
            cmd = next(c for c, info in ADMIN_COMMANDS.items() if cmd in info["alias"])
            if not self.userInfo["isadmin"]:
                event.channel.send(Reply(ReplyType.TEXT, "[MJ] 您没有权限执行该操作，请先进行管理员认证"), event.message)
                event.bypass()
            
            # 在 handle_command 函数中添加 mj_g_info 处理逻辑
            if cmd == "mj_g_info":
                # 直接在这里加载最新的用户数据
                if os.path.exists(self.user_datas_path):
                    with open(self.user_datas_path, "rb") as f:
                        self.user_datas = pickle.load(f)
                else:
                    self.user_datas = {}  
                user_infos = []
                for uid_group, data in self.user_datas.items():
                    # 获取用户昵称、剩余次数、群名和失效日期
                    user_nickname = data.get("mj_datas", {}).get("nickname", "未知昵称")
                    limit = data.get("mj_datas", {}).get("limit", "未知次数")
                    group_name = data.get("mj_datas", {}).get("group_name", "非群聊")
                    expire_time = data.get("mj_datas", {}).get("expire_time", "未知日期")

                    # 使用格式化函数将日期转换为需要的格式
                    formatted_expire_time = self.format_date(expire_time)

                    # 拼接用户信息
                    user_infos.append(f"昵称: {user_nickname}, 群名: {group_name}, 剩余次数: {limit}次, 失效日期: {formatted_expire_time}")


                # 将所有用户信息拼接成一个字符串
                if user_infos:
                    info_text = "当前用户信息:\n" + "\n".join(user_infos)
                else:
                    info_text = "没有找到用户数据。"
                
                event.channel.send(Reply(ReplyType.TEXT, info_text), event.message)
                event.bypass()

            elif cmd == "mj_s_limit":
                if len(args) < 1:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 请输入需要设置的数量"), event.message)
                    event.bypass()
                
                try:
                    limit = int(args[0])
                except ValueError:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 请输入有效的数字"), event.message)
                    event.bypass()
                
                if limit < 0:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 数量不能小于0"), event.message)
                    event.bypass()
                
                # 更新系统的 daily_limit
                self.nconfig["daily_limit"] = limit
                
                # 更新所有用户（不区分群聊或私聊）的 limit
                for uid_group, data in self.user_datas.items():
                    if "mj_datas" in data:  # 确保 mj_datas 字段存在
                        self.user_datas[uid_group]["mj_datas"]["default_limit"] = limit
                        self.user_datas[uid_group]["mj_datas"]["limit"] = limit
                
                # 保存到文件
                write_pickle(self.user_datas_path, self.user_datas)
                write_file(self.json_path, self.nconfig)
                
                event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 每日使用次数已设置为 {limit} 次"), event.message)
                event.bypass()

            elif cmd == "mj_r_limit":
                if len(args) < 1:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 请输入ALL或具体用户昵称"), event.message)
                    event.bypass()
                
                reset_target = args[0].strip()

                if reset_target.upper() == "ALL":
                    # 重置所有用户的 limit
                    for uid_group, data in self.user_datas.items():
                        if "mj_datas" in data:
                            self.user_datas[uid_group]["mj_datas"]["limit"] = self.nconfig["daily_limit"]
                    write_pickle(self.user_datas_path, self.user_datas)
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 所有用户每日使用次数已重置为 {self.nconfig['daily_limit']} 次"), event.message)
                    event.bypass()
                
                else:
                    # 重置指定用户的所有群聊和私聊记录
                    user_found = False
                    for uid_group, data in self.user_datas.items():
                        if data["mj_datas"].get("nickname") == reset_target:
                            self.user_datas[uid_group]["mj_datas"]["limit"] = self.nconfig["daily_limit"]
                            user_found = True
                    
                    if user_found:
                        write_pickle(self.user_datas_path, self.user_datas)
                        event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 用户 {reset_target} 的每日使用次数已重置为 {self.nconfig['daily_limit']} 次"), event.message)
                        event.bypass()
                    else:
                        event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 未找到用户 {reset_target}"), event.message)
                        event.bypass()


            elif cmd == "set_mj_admin_password":
                if len(args) < 1:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 请输入需要设置的密码"), event.message)
                    event.bypass()
                password = args[0]
                if self.isgroup:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 为避免密码泄露，请勿在群聊中进行修改"), event.message)
                    event.bypass()
                if len(password) < 6:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 密码长度不能小于6位"), event.message)
                    event.bypass()
                if password == self.nconfig['mj_admin_password']:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 新密码不能与旧密码相同"), event.message)
                    event.bypass()
                self.nconfig["mj_admin_password"] = password
                write_file(self.json_path, self.nconfig)
                event.channel.send(Reply(ReplyType.TEXT, "[MJ] 管理员口令设置成功"), event.message)
                event.bypass()
            elif cmd == "mj_stop":
                self.ismj = False
                event.channel.send(Reply(ReplyType.TEXT, "[MJ] 服务已暂停"), event.message)
                event.bypass()
            elif cmd == "mj_enable":
                self.ismj = True
                event.channel.send(Reply(ReplyType.TEXT, "[MJ] 服务已启用"), event.message)
                event.bypass()
            elif cmd == "mj_g_admin_list" and not self.isgroup:
                adminUser = self.roll["mj_admin_users"]
                t = "\n"
                nameList = t.join(f'{index+1}. {data["user_nickname"]}' for index, data in enumerate(adminUser))
                event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 管理员用户\n{nameList}"), event.message)
                event.bypass()
            elif cmd == "mj_c_admin_list" and not self.isgroup:
                self.roll["mj_admin_users"] = []
                write_pickle(self.roll_path, self.roll)
                event.channel.send(Reply(ReplyType.TEXT, "[MJ] 管理员用户已清空"), event.message)
                event.bypass()
            elif cmd == "mj_s_admin_list" and not self.isgroup:
                user_name = args[0] if args and args[0] else ""
                adminUsers = self.roll["mj_admin_users"]
                buser = self.roll["mj_busers"]
                if not args or len(args) < 1:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 请输入需要设置的管理员名称或ID"), event.message)
                    event.bypass()
                index = -1
                for i, user in enumerate(adminUsers):
                    if user["user_id"] == user_name or user["user_nickname"] == user_name:
                        index = i
                        break
                if index >= 0:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 管理员[{adminUsers[index]['user_nickname']}]已在列表中"), event.message)
                    event.bypass()
                for i, user in enumerate(buser):
                    if user == user_name:
                        index = i
                        break
                if index >= 0:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 用户[{user_name}]已在黑名单中，如需添加请先进行移除"), event.message)
                    event.bypass()
                userInfo = {
                    "user_id": user_name,
                    "user_nickname": user_name
                }

                userInfo = search_friends(user_name)
                # 判断user_name是否在列表中
                if not userInfo or not userInfo["user_id"]:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 用户[{user_name}]不存在通讯录中"), event.message)
                    event.bypass()
                adminUsers.append(userInfo)
                self.roll["mj_admin_users"] = adminUsers
                # 写入用户列表
                write_pickle(self.roll_path, self.roll)
                event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 管理员[{userInfo['user_nickname']}]已添加到列表中"), event.message)
                event.bypass()
            elif cmd == "mj_r_admin_list" and not self.isgroup:
                text = ""
                adminUsers = self.roll["mj_admin_users"]
                if len(args) < 1:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 请输入需要移除的管理员名称或ID或序列号"), event.message)
                    event.bypass()
                if args and args[0]:
                    if args[0].isdigit():
                        index = int(args[0]) - 1
                        if index < 0 or index >= len(adminUsers):
                            event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 序列号[{args[0]}]不存在"), event.message)
                            event.bypass()
                        user_name = adminUsers[index]['user_nickname']
                        del adminUsers[index]
                        self.roll["mj_admin_users"] = adminUsers
                        write_pickle(self.roll_path, self.roll)
                        text = f"[MJ] 管理员[{user_name}]已从列表中移除"
                    else:
                        user_name = args[0]
                        index = -1
                        for i, user in enumerate(adminUsers):
                            if user["user_nickname"] == user_name or user["user_id"] == user_name:
                                index = i
                                break
                        if index >= 0:
                            del adminUsers[index]
                            text = f"[MJ] 管理员[{user_name}]已从列表中移除"
                            self.roll["mj_admin_users"] = adminUsers
                            write_pickle(self.roll_path, self.roll)
                        else:
                            event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 管理员[{user_name}]不在列表中"), event.message)
                            event.bypass()
                event.channel.send(Reply(ReplyType.TEXT, text), event.message)
                event.bypass()
            elif cmd == "mj_g_wgroup" and not self.isgroup:
                text = ""
                groups = self.roll["mj_groups"]
                if len(groups) == 0:
                    text = "[MJ] 白名单群组：无"
                else:
                    t = "\n"
                    nameList = t.join(f'{index+1}. {group}' for index, group in enumerate(groups))
                    text = f"[MJ] 白名单群组\n{nameList}"
                event.channel.send(Reply(ReplyType.TEXT, text), event.message)
                event.bypass() 
            elif cmd == "mj_c_wgroup":
                self.roll["mj_groups"] = []
                write_pickle(self.roll_path, self.roll)
                event.channel.send(Reply(ReplyType.TEXT, "[MJ] 群组白名单已清空"), event.message)
                event.bypass()
            elif cmd == "mj_s_wgroup":
                groups = self.roll["mj_groups"]
                bgroups = self.roll["mj_bgroups"]
                if not self.isgroup and len(args) < 1:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 请输入需要设置的群组名称"), event.message)
                    event.bypass()
                if self.isgroup:
                    group_name = self.userInfo["group_name"]
                if args and args[0]:
                    group_name = args[0]
                if group_name in groups:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 群组[{group_name}]已在白名单中"), event.message)
                    event.bypass()
                if group_name in bgroups:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 群组[{group_name}]已在黑名单中，如需添加请先进行移除"), event.message)
                    event.bypass()

                roomid = event.message.room_id
                chatrooms = self.get_group_name(roomid)

                if len(chatrooms) == 0:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 群组[{group_name}]不存在"), event.message)
                    event.bypass()
                groups.append(group_name)
                self.roll["mj_groups"] = groups
                write_pickle(self.roll_path, self.roll)
                event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 群组[{group_name}]已添加到白名单"), event.message)
                event.bypass()
            elif cmd == "mj_r_wgroup":
                groups = self.roll["mj_groups"]
                if not self.isgroup and len(args) < 1:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 请输入需要移除的群组名称或序列号"), event.message)
                    event.bypass()
                if self.isgroup:
                    group_name = self.userInfo["group_name"]
                if args and args[0]:
                    if args[0].isdigit():
                        index = int(args[0]) - 1
                        if index < 0 or index >= len(groups):
                            event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 序列号[{args[0]}]不在白名单中"), event.message)
                            event.bypass()
                        group_name = groups[index]
                    else:
                        group_name = args[0]
                if group_name in groups:
                    groups.remove(group_name)
                    self.roll["mj_groups"] = groups
                    write_pickle(self.roll_path, self.roll)
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 群组[{group_name}]已从白名单中移除"), event.message)
                    event.bypass()
                else:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 群组[{group_name}]不在白名单中"), event.message)
                    event.bypass()
            elif cmd == "mj_g_bgroup" and not self.isgroup:
                text = ""
                bgroups = self.roll["mj_bgroups"]
                if len(bgroups) == 0:
                    text = "[MJ] 黑名单群组：无"
                else:
                    t = "\n"
                    nameList = t.join(f'{index+1}. {group}' for index, group in enumerate(bgroups))
                    text = f"[MJ] 黑名单群组\n{nameList}"
                event.channel.send(Reply(ReplyType.TEXT, text), event.message)
                event.bypass()
            elif cmd == "mj_c_bgroup":
                self.roll["mj_bgroups"] = []
                write_pickle(self.roll_path, self.roll)
                event.channel.send(Reply(ReplyType.TEXT, "[MJ] 已清空黑名单群组"), event.message)
                event.bypass()
            elif cmd == "mj_s_bgroup":
                groups = self.roll["mj_groups"]
                bgroups = self.roll["mj_bgroups"]
                if not self.isgroup and len(args) < 1:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 请输入需要设置的群组名称"), event.message)
                    event.bypass()
                if self.isgroup:
                    group_name = self.userInfo["group_name"]
                if args and args[0]:
                    group_name = args[0]
                if group_name in groups:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 群组[{group_name}]已在白名单中，如需添加请先进行移除"), event.message)
                    event.bypass()
                if group_name in bgroups:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 群组[{group_name}]已在黑名单中"), event.message)
                    event.bypass()

                roomid = event.message.room_id
                chatrooms = self.get_group_name(roomid)

                if len(chatrooms) == 0:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 群组[{group_name}]不存在"), event.message)
                    event.bypass()

                bgroups.append(group_name)
                self.roll["mj_bgroups"] = bgroups
                write_pickle(self.roll_path, self.roll)
                event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 群组[{group_name}]已添加到黑名单"), event.message)
                event.bypass()
            elif cmd == "mj_r_bgroup":
                bgroups = self.roll["mj_bgroups"]
                if not self.isgroup and len(args) < 1:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 请输入需要移除的群组名称或序列号"), event.message)
                    event.bypass()
                if self.isgroup:
                    group_name = self.userInfo["group_name"]
                if args and args[0]:
                    if args[0].isdigit():
                        index = int(args[0]) - 1
                        if index < 0 or index >= len(bgroups):
                            event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 序列号[{args[0]}]不在黑名单中"), event.message)
                            event.bypass()
                        group_name = bgroups[index]
                    else:
                        group_name = args[0]
                if group_name in bgroups:
                    bgroups.remove(group_name)
                    self.roll["mj_bgroups"] = bgroups
                    write_pickle(self.roll_path, self.roll)
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 群组[{group_name}]已从黑名单中移除"), event.message)
                    event.bypass()
                else:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 群组[{group_name}]不在黑名单中"), event.message)
                    event.bypass()
            elif cmd == "mj_g_buser" and not self.isgroup:
                busers = self.roll["mj_busers"]
                if len(busers) == 0:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 黑名单用户：无"), event.message)
                    event.bypass()
                else:
                    t = "\n"
                    nameList = t.join(f'{index+1}. {data}' for index, data in enumerate(busers))
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 黑名单用户\n{nameList}"), event.message)
                    event.bypass()
            elif cmd == "mj_g_wuser" and not self.isgroup:
                users = self.roll["mj_users"]
                if len(users) == 0:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 白名单用户：无"), event.message)
                    event.bypass()
                else:
                    t = "\n"
                    nameList = t.join(f'{index+1}. {data}' for index, data in enumerate(users))
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 白名单用户\n{nameList}"), event.message)
                    event.bypass()
            elif cmd == "mj_c_wuser":
                self.roll["mj_users"] = []
                write_pickle(self.roll_path, self.roll)
                event.channel.send(Reply(ReplyType.TEXT, "[MJ] 用户白名单已清空"), event.message)
                event.bypass()
            elif cmd == "mj_c_buser":
                self.roll["mj_busers"] = []
                write_pickle(self.roll_path, self.roll)
                event.channel.send(Reply(ReplyType.TEXT, "[MJ] 用户黑名单已清空"), event.message)
                event.bypass()
            elif cmd == "mj_s_wuser":
                user_name = args[0] if args and args[0] else ""
                users = self.roll["mj_users"]
                busers = self.roll["mj_busers"]
                if not args or len(args) < 1:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 请输入需要设置的用户名称或ID"), event.message)
                    event.bypass()
                index = -1
                for i, user in enumerate(users):
                    if user == user_name:
                        index = i
                        break
                if index >= 0:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 用户[{user_name}]已在白名单中"), event.message)
                    event.bypass()
                for i, user in enumerate(busers):
                    if user == user_name:
                        index = i
                        break
                if index >= 0:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 用户[{user_name}]已在黑名单中，如需添加请先移除黑名单"), event.message)
                    event.bypass()

                userInfo = search_friends(user_name)
                # 判断user_name是否在列表中
                if not userInfo or not userInfo["user_id"]:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 用户[{user_name}]不存在通讯录中"), event.message)
                    event.bypass()
                users.append(user_name)
                self.roll["mj_users"] = users
                write_pickle(self.roll_path, self.roll)
                event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 用户[{user_name}]已添加到白名单"), event.message)
                event.bypass()
            elif cmd == "mj_s_buser":
                user_name = args[0] if args and args[0] else ""
                users = self.roll["mj_users"]
                busers = self.roll["mj_busers"]
                if not args or len(args) < 1:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 请输入需要设置的用户名称或ID"), event.message)
                    event.bypass()
                index = -1
                for i, user in enumerate(users):
                    if user == user_name:
                        index = i
                        break
                if index >= 0:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 用户[{user_name}]已在白名单中，如需添加请先移除白名单"), event.message)
                    event.bypass()
                for i, user in enumerate(busers):
                    if user == user_name:
                        index = i
                        break
                if index >= 0:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 用户[{user_name}]已在黑名单中"), event.message)
                    event.bypass()

                userInfo = search_friends(user_name)
                # 判断user_name是否在列表中
                if not userInfo or not userInfo["user_id"]:
                    event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 用户[{user_name}]不存在通讯录中"), event.message)
                    event.bypass()
                busers.append(user_name)
                self.roll["mj_busers"] = busers
                write_pickle(self.roll_path, self.roll)
                event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 用户[{user_name}]已添加到黑名单"), event.message)
                event.bypass()
            elif cmd == "mj_r_wuser":
                text = ""
                users = self.roll["mj_users"]
                if len(args) < 1:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 请输入需要移除的用户名称或ID或序列号"), event.message)
                    event.bypass()
                if args and args[0]:
                    if args[0].isdigit():
                        index = int(args[0]) - 1
                        if index < 0 or index >= len(users):
                            event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 序列号[{args[0]}]不存在"), event.message)
                            event.bypass()
                        user_name = users[index]
                        del users[index]
                        self.roll["mj_users"] = users
                        write_pickle(self.roll_path, self.roll)
                        text = f"[MJ] 用户[{user_name}]已从白名单中移除"
                    else:
                        user_name = args[0]
                        index = -1
                        for i, user in enumerate(users):
                            if user == user_name:
                                index = i
                                break
                        if index >= 0:
                            del users[index]
                            text = f"[MJ] 用户[{user_name}]已从白名单中移除"
                            self.roll["mj_users"] = users
                            write_pickle(self.roll_path, self.roll)
                        else:
                            event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 用户[{user_name}]不在白名单中"), event.message)
                            event.bypass()
                event.channel.send(text, event.message)
                event.bypass()
            elif cmd == "mj_r_buser":
                text = ""
                busers = self.roll["mj_busers"]
                if len(args) < 1:
                    event.channel.send(Reply(ReplyType.TEXT, "[MJ] 请输入需要移除的用户名称或ID或序列号"), event.message)
                    event.bypass()
                if args and args[0]:
                    if args[0].isdigit():
                        index = int(args[0]) - 1
                        if index < 0 or index >= len(busers):
                            event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 序列号[{args[0]}]不存在"), event.message)
                            event.bypass()
                        user_name = busers[index]
                        del busers[index]
                        self.roll["mj_busers"] = busers
                        write_pickle(self.roll_path, self.roll)
                        text = f"[MJ] 用户[{user_name}]已从黑名单中移除"
                    else:
                        user_name = args[0]
                        index = -1
                        for i, user in enumerate(busers):
                            if user == user_name:
                                index = i
                                break
                        if index >= 0:
                            del busers[index]
                            text = f"[MJ] 用户[{user_name}]已从黑名单中移除"
                            self.roll["mj_busers"] = busers
                            write_pickle(self.roll_path, self.roll)
                        else:
                            event.channel.send(Reply(ReplyType.TEXT, f"[MJ] 用户[{user_name}]不在黑名单中"), event.message)
                            event.bypass()
                event.channel.send(Reply(ReplyType.TEXT, text), event.message)
                event.bypass()
            else:
                return "Bye"

    def get_group_name(self, roomid):
        # 确保 contacts 已加载
        channel = WrestChannel()
        if not hasattr(self, 'contacts') or not self.contacts:
            channel.update_contacts()  # 加载联系人数据

        # 查找 roomid 对应的群信息
        group_info = channel.contacts.get(roomid, {})
        group_name = group_info.get('name', '')  # 如果没有 name，返回空字符串
        return group_name


    def authenticate(self, userInfo, args) -> Tuple[bool, str]:
        isgroup = userInfo["isgroup"]
        isadmin = userInfo["isadmin"]
        if isgroup:
            return False, "[MJ] 为避免密码泄露，请勿在群聊中认证"

        if isadmin:
            return False, "[MJ] 管理员账号无需认证"

        if len(args) != 1:
            return False, "[MJ] 请输入密码"

        password = args[0]
        if password == self.nconfig['mj_admin_password']:
            self.roll["mj_admin_users"].append({
                "user_id": userInfo["user_id"],
                "user_nickname": userInfo["user_nickname"]
            })
            write_pickle(self.roll_path, self.roll)
            return True, f"[MJ] 认证成功"
        else:
            return False, "[MJ] 认证失败"

    
    def get_user_info(self, event: Event):
        # 获取当前时间戳
        if os.path.exists(self.user_datas_path):
            with open(self.user_datas_path, "rb") as f:
                self.user_datas = pickle.load(f)
        else:
            self.user_datas = {}
        

        groups = self.roll["mj_groups"]
        bgroups = self.roll["mj_bgroups"]
        users = self.roll["mj_users"]      
        busers = self.roll["mj_busers"]
        mj_admin_users = self.roll["mj_admin_users"]
        
        context = event.message
        msg = context
        isgroup = context.get("isgroup", False)
        # 写入用户信息，企业微信没有sender_name，所以使用sender_id代替
        uid = msg.sender_id if not isgroup else msg.sender_id
        uname = (msg.sender_name if msg.sender_name else uid) if not isgroup else msg.sender_name
        roomid = msg.room_id if isgroup else "非群聊"
        group_name = self.get_group_name(roomid) if isgroup else "非群聊"
        uid_group = f"{uid}_{group_name}"
        
        logger.debug(f"[MJ] Type of users: {type(users)}, Content: {users}")
        logger.debug(f"[MJ] UID: {uid}, User data keys: {list(self.user_datas.keys())}")

        # 如果没有找到数据，调用更新方法初始化数据
        if uid_group not in self.user_datas:
            self.update_user_data(uid, uname, isgroup, group_name)

        # 保存用户数据
        with open(self.user_datas_path, "wb") as f:
            pickle.dump(self.user_datas, f)

        # 获取用户的limit
        limit = self.user_datas[uid_group]["mj_datas"]["limit"] if self.user_datas[uid_group]["mj_datas"]["limit"] > 0 else False

        # 保存用户数据
        write_pickle(self.user_datas_path, self.user_datas)

        userInfo = {
            "user_id": uid,
            "user_nickname": uname,
            "isgroup": isgroup,
            "group_id": msg.sender_id if isgroup else "",
            "group_name": group_name,
            "limit": limit,
            "isadmin": uid in [user["user_id"] for user in mj_admin_users]
        }

        # 判断白名单和黑名单用户

        # 判断白名单用户
        if isinstance(users, list):
            if all(isinstance(user, dict) for user in users):
                userInfo['iswuser'] = uname in [user["user_nickname"] for user in users]
            else:
                userInfo['iswuser'] = uname in users  # 如果 users 是字符串列表
        else:
            userInfo['iswuser'] = False

        # 判断黑名单用户
        if isinstance(busers, list):
            if all(isinstance(user, dict) for user in busers):
                userInfo['isbuser'] = uname in [user["user_nickname"] for user in busers]
            else:
                userInfo['isbuser'] = uname in busers  # 如果 busers 是字符串列表
        else:
            userInfo['isbuser'] = False


        userInfo['iswgroup'] = group_name in groups
        userInfo['isbgroup'] = group_name in bgroups
        
        return userInfo
    
    def update_user_data(self, uid, nickname, isgroup, group_name=None):
        now = datetime.now()
        uid_group = f"{uid}_{group_name if isgroup else '非群聊'}"
        
        # 遍历所有用户数据，更新所有相关UID
        for user_uid, user_data in list(self.user_datas.items()):
            if user_data['mj_datas']['nickname'] == nickname:
                # 无论群聊或私聊，更新UID（保持原来的群聊/私聊数据结构）
                old_uid_group = user_uid
                updated_data = self.user_datas.pop(old_uid_group)
                new_uid_group = f"{uid}_{updated_data['mj_datas']['group_name'] if updated_data['mj_datas']['isgroup'] else '非群聊'}"
                
                # 更新UID和最后更新时间
                updated_data['mj_datas']['update_time'] = now
                self.user_datas[new_uid_group] = updated_data

        # 如果当前群聊或私聊没有记录，创建新的数据
        if uid_group not in self.user_datas:
            self.user_datas[uid_group] = {
                'mj_datas': {
                    'nickname': nickname,
                    'isgroup': isgroup,
                    'group_name': group_name if isgroup else '非群聊',
                    'default_limit': self.nconfig['daily_limit'],
                    'limit': self.nconfig['daily_limit'],
                    'expire_time': (now + timedelta(days=30)).strftime("%Y/%m/%d %H:%M:%S"),
                    'update_time': now.strftime("%Y/%m/%d %H:%M:%S")
                }
            }


    def update_limit(self, uid, group_name, amount):

        # 直接在这里加载最新的用户数据
        if os.path.exists(self.user_datas_path):
            with open(self.user_datas_path, "rb") as f:
                self.user_datas = pickle.load(f)
        else:
            self.user_datas = {}        
        
        now = datetime.now()
        uid_group = f"{uid}_{group_name if group_name else '非群聊'}"  # 使用组合键
        logger.debug(f"[MJ] Attempting to update limit for: {uid_group}")
        # 检查用户是否存在
        if uid_group in self.user_datas:
            # 更新用户的 limit 和 update_time
            self.user_datas[uid_group]['mj_datas']['limit'] -= amount
            self.user_datas[uid_group]['mj_datas']['update_time'] = now.strftime("%Y/%m/%d %H:%M:%S")
            logger.debug(f"[MJ] Updated limit for {uid_group}: {self.user_datas[uid_group]['mj_datas']['limit']}")
        else:
            logger.warning(f"[MJ] User {uid_group} not found.")     

    def format_date(self, date_obj):
        if isinstance(date_obj, datetime):  # 确保 `datetime` 是从 `datetime` 模块导入的类
            return date_obj.strftime("%Y/%m/%d %H:%M:%S")
        elif isinstance(date_obj, str):
            try:
                # 如果是字符串，确保它能够被解析为正确的格式，否则抛出错误
                datetime.strptime(date_obj, "%Y/%m/%d %H:%M:%S")
                return date_obj
            except ValueError:
                raise logger.error(f"String format is incorrect: {date_obj}")
        else:
            raise logger.error(f"Expected str or datetime, but got {type(date_obj)}")