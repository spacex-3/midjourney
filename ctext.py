
import json
import pickle
import requests
from plugins import *
from plugins import register, Plugin, Event, Reply, ReplyType, logger

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


def search_friends(name):
    userInfo = {
        "user_id": "",
        "user_nickname": ""
    }
    # 设置 Wrest 请求 URL 和 Headers
    url = "http://127.0.0.1:7600/wcf/db_query_sql"
    headers = {
        "accept": "application/json",
        "Content-Type": "application/json"
    }
    
    # 构建 SQL 查询，根据用户名或备注名进行搜索
    sql_query = f"""
        SELECT UserName, NickName 
        FROM Contact 
        WHERE NickName = '{name}' OR Remark = '{name}'
    """
    payload = {
        "db": "MicroMsg.sb",
        "sql": sql_query
    }
    
    try:
        # 发送 POST 请求
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        # 解析返回结果
        data = response.json()
        if data and isinstance(data, list) and len(data) > 0:
            # 取第一个匹配的结果
            user = data[0]
            userInfo["user_id"] = user.get("UserName", "")
            userInfo["user_nickname"] = user.get("NickName", "")
    except requests.RequestException as e:
        print(f"Error during request: {e}")
    except KeyError as e:
        print(f"Key error in response: {e}")
    
    return userInfo



def env_detection(self, event: Event):
    
    # 如果用户是管理员或者在白名单用户列表中，则不受限制
    if self.userInfo["isadmin"] or self.userInfo["iswuser"]:
        return True
    
    # 如果用户不在白名单用户列表中且使用次数已用完
    if not self.userInfo["limit"]:
        # 检查是否在白名单群组中
        if self.userInfo["iswgroup"]:
            return True
        else:
            event.channel.send(Reply(ReplyType.TEXT, "[MJ] 您今日的使用次数已用完，请明日再来"), event.message)
            event.bypass()
            return False

    return True