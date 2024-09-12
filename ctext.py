# encoding:utf-8
import os
import re
import io
import json
import base64
import pickle
import requests
from PIL import Image
from plugins import *
from lib import itchat
from lib.itchat.content import *
from bridge.reply import Reply, ReplyType
from config import conf
from common.log import logger
from datetime import datetime


COMMANDS = {
    "mj_help": {
        "alias": ["mj_help", "mj帮助", "mj文档","mjhelp"],
        "desc": "mj帮助",
    },
    "mj_admin_cmd": {
        "alias": ["mj_admin_cmd", "mj管理员指令"],
        "desc": "mj管理员指令",
    },
    "mj_admin_password": {
        "alias": ["mj_admin_password", "mj管理员认证"],
        "args": ["口令"],
        "desc": "mj管理员认证",
    },
}


ADMIN_COMMANDS = {
    "mj_g_info": {
        "alias": ["mj_g_info", "查询用户信息"],
        "desc": "查询数据库中用户昵称和对应的剩余次数",
    },
    "mj_stop": {
        "alias": ["mj_stop", "stop_mj", "暂停mj服务"],
        "desc": "暂停mj服务",
    },
    "mj_enable": {
        "alias": ["mj_enable", "enable_mj", "启用mj服务"],
        "desc": "启用mj服务",
    },
    "set_mj_admin_password": {
        "alias": ["set_mj_admin_password", "设置管理员口令"],
        "args": ["口令"],
        "desc": "修改管理员口令",
    },
    "mj_g_admin_list": {
        "alias": ["mj_g_admin_list", "查询管理员列表"],
        "desc": "查询管理员列表",
    },
    "mj_s_admin_list": {
        "alias": ["mj_s_admin_list", "添加管理员"],
        "args": ["用户ID或昵称"],
        "desc": "添加管理员",
    },
    "mj_r_admin_list": {
        "alias": ["mj_r_admin_list", "移除管理员"],
        "args": ["用户ID或昵称或序列号"],
        "desc": "移除管理员",
    },
    "mj_c_admin_list": {
        "alias": ["mj_c_admin_list", "清空管理员"],
        "desc": "清空管理员",
    },
    "mj_s_limit": {
        "alias": ["mj_s_limit", "设置每日作图数限制"],
        "args": ["限制值"],
        "desc": "设置每日作图数限制",
    },
    "mj_r_limit": {
        "alias": ["mj_r_limit", "清空重置用户作图数限制"],
        "desc": "清空重置用户作图数限制",
    },
    "mj_g_wgroup": {
        "alias": ["mj_g_wgroup", "查询白名单群组"],
        "desc": "查询白名单群组",
    },
    "mj_s_wgroup": {
        "alias": ["mj_s_wgroup", "添加白名单群组"],
        "args": ["群组名称"],
        "desc": "添加白名单群组",
    },
    "mj_r_wgroup": {
        "alias": ["mj_r_wgroup", "移除白名单群组"],
        "args": ["群组名称或序列号"],
        "desc": "移除白名单群组",
    },
    "mj_c_wgroup": {
        "alias": ["mj_c_wgroup", "清空白名单群组"],
        "desc": "清空白名单群组",
    },
    "mj_g_wuser": {
        "alias": ["mj_g_wuser", "查询白名单用户"],
        "desc": "查询白名单用户",
    },
    "mj_s_wuser": {
        "alias": ["mj_s_wuser", "添加白名单用户"],
        "args": ["用户ID或昵称"],
        "desc": "添加白名单用户",
    },
    "mj_r_wuser": {
        "alias": ["mj_r_wuser", "移除白名单用户"],
        "args": ["用户ID或昵称或序列号"],
        "desc": "移除白名单用户",
    },
    "mj_c_wuser": {
        "alias": ["mj_c_wuser", "清空白名单用户"],
        "desc": "清空白名单用户",
    },
    "mj_g_bgroup": {
        "alias": ["mj_g_bgroup", "查询黑名单群组"],
        "desc": "查询黑名单群组",
    },
    "mj_s_bgroup": {
        "alias": ["mj_s_bgroup", "添加黑名单群组"],
        "args": ["群组名称"],
        "desc": "添加黑名单群组",
    },
    "mj_r_bgroup": {
        "alias": ["mj_r_bgroup", "移除黑名单群组"],
        "args": ["群组名称或序列号"],
        "desc": "移除黑名单群组",
    },
    "mj_c_bgroup": {
        "alias": ["mj_c_bgroup", "清空黑名单群组"],
        "desc": "清空黑名单群组",
    },
    "mj_g_buser": {
        "alias": ["mj_g_buser", "查询黑名单用户"],
        "desc": "查询黑名单用户",
    },
    "mj_s_buser": {
        "alias": ["mj_s_buser", "添加黑名单用户"],
        "args": ["用户ID或昵称"],
        "desc": "添加黑名单用户",
    },
    "mj_r_buser": {
        "alias": ["mj_r_buser", "移除黑名单用户"],
        "args": ["用户ID或昵称或序列号"],
        "desc": "移除黑名单用户",
    },
    "mj_c_buser": {
        "alias": ["mj_c_buser", "清空黑名单用户"],
        "desc": "清空黑名单用户",
    },
}

def read_pickle(path):
    with open(path, "rb") as f:
        data = pickle.load(f)
    return data


def write_pickle(path, content):
    with open(path, "wb") as f:
        pickle.dump(content, f)
    return True


def read_file(path):
    with open(path, mode="r", encoding="utf-8") as f:
        return f.read()


def write_file(path, content):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(content, f, indent=4)
    return True
def Text(msg, e_context: EventContext):
    return send(msg, e_context, ReplyType.TEXT)


def Image_file(msg, e_context: EventContext):
    return send(msg, e_context, ReplyType.IMAGE)


def Image_url(msg, e_context: EventContext):
    return send(msg, e_context, ReplyType.IMAGE_URL)


def Info(msg, e_context: EventContext):
    return send(msg, e_context, ReplyType.INFO)


def Error(msg, e_context: EventContext):
    return send(msg, e_context, ReplyType.ERROR)


def send(reply, e_context: EventContext, reply_type=ReplyType.TEXT, action=EventAction.BREAK_PASS):
    if isinstance(reply, Reply):
        if not reply.type and reply_type:
            reply.type = reply_type
    else:
        reply = Reply(reply_type, reply)
    e_context["reply"] = reply
    e_context.action = action
    return


def Textr(msg, e_context: EventContext):
    return send_reply(msg, e_context, ReplyType.TEXT)


def Image_filer(msg, e_context: EventContext):
    return send_reply(msg, e_context, ReplyType.IMAGE)


def Image_url_reply(msg, e_context: EventContext):
    return send_reply(msg, e_context, ReplyType.IMAGE_URL)


def Info_reply(msg, e_context: EventContext):
    return send_reply(msg, e_context, ReplyType.INFO)


def Error_reply(msg, e_context: EventContext):
    return send_reply(msg, e_context, ReplyType.ERROR)


def send_reply(reply, e_context: EventContext, reply_type=ReplyType.TEXT):
    if isinstance(reply, Reply):
        if not reply.type and reply_type:
            reply.type = reply_type
    else:
        reply = Reply(reply_type, reply)
    channel = e_context['channel']
    context = e_context['context']
    # reply的包装步骤
    rd = channel._decorate_reply(context, reply)
    # reply的发送步骤
    return channel._send_reply(context, rd)

def search_friends(name):
    userInfo = {
        "user_id": "",
        "user_nickname": ""
    }
    # 判断是id还是昵称
    if name.startswith("@"):
        friends = itchat.search_friends(userName=name)
    else:
        friends = itchat.search_friends(name=name)
    if friends and len(friends) > 0:
        if isinstance(friends, list):
            userInfo["user_id"] = friends[0]["UserName"]
            userInfo["user_nickname"] = friends[0]["NickName"]
        else:
            userInfo["user_id"] = friends["UserName"]
            userInfo["user_nickname"] = friends["NickName"]
    return userInfo


def env_detection(self, e_context: EventContext):
    now = datetime.now()  # 获取当前时间
    reply = None

    # 获取当前的 uid_group（基于用户 ID 和群组信息的组合键）
    uid_group = f"{self.userInfo['user_id']}_{self.userInfo['group_name'] if self.userInfo['isgroup'] else '非群聊'}"

    # 1. 管理员优先，无限制
    if self.userInfo["isadmin"]:
        return True

    # 2. 黑名单用户，无论是否在白名单群组，直接禁止使用
    if self.userInfo["isbuser"]:
        logger.debug("[MJ] Blocked by user blacklist.")
        reply = Reply(ReplyType.ERROR, "[MJ] 您在黑名单中，无法使用此功能")
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
        return False

    # 3. 黑名单群组，禁止白名单用户和普通用户使用
    if self.isgroup and self.userInfo["isbgroup"]:
        logger.debug("[MJ] Blocked by group blacklist.")
        reply = Reply(ReplyType.ERROR, "[MJ] 您所在的群组在黑名单中，无法使用此功能")
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
        return False

    # 4. 白名单用户，可以无限制使用，但不能在黑名单群组中使用
    if self.userInfo["iswuser"]:
        if self.isgroup and self.userInfo["isbgroup"]:
            logger.debug("[MJ] Blocked by group blacklist for whitelist user.")
            reply = Reply(ReplyType.ERROR, "[MJ] 您所在的群组在黑名单中，无法使用此功能")
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            return False
        # 白名单用户可以在私聊、普通群聊、白名单群聊中使用，无限制
        return True

    # 5. 普通用户，检查使用次数和过期时间
    # 比较时将字符串转换为 datetime 对象
    if uid_group in self.user_datas:
        expire_time = self.user_datas[uid_group]["mj_datas"].get("expire_time", None)

        # 如果 expire_time 是字符串，先将它转换为 datetime 对象
        if isinstance(expire_time, str):
            expire_time = datetime.strptime(expire_time, "%Y/%m/%d %H:%M:%S")

        # 如果 expire_time 存在并且过期时间早于当前时间
        if expire_time and expire_time < now:
            reply = Reply(ReplyType.ERROR, "[MJ] 您的使用期限已到，请联系管理员更新权限")
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            return False

    # 6. 检查用户的使用次数
    if not self.userInfo["limit"]:
        if self.userInfo["iswgroup"]:
            # 在白名单群组中，用户可以无视次数限制
            return True
        else:
            reply = Reply(ReplyType.ERROR, "[MJ] 您今日的使用次数已用完，请明日再来")
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            return False

    return True
