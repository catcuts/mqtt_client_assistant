# -*- coding:utf-8 -*-

from paho.mqtt.client import connack_string, error_string
import paho.mqtt.client as mqttc
from queue import Queue
import threading
import msgpack
import json
import time
import sys
import re

__author__ = "lth liu2066@foxmail.com"

ADDR = "192.168.110.12"  # 地址
PORT = 1883  # 端口
USERNAME = ""  # 用户名
PASSWORD = ""  # 密码
DEFAULT_TOPICS = "/test/topic"  # 默认订阅
# DEFAULT_TOPICS = "/test/topic1, /test/topic2"  # 默认订阅(列表形式, 逗号分隔)
DEFAULT_TOPICS_QOS = 0

CANCEL_CHAR = "\s*<<<\s*cancel\s*"
DEBUG = False
LANG = "cn"

HELP = {
    "PRESS ENTER 回车": "go to edit your command 进入编辑命令模式",
    "config 配置": "config --debug=true|false",
    "subscribe 订阅": "subscribe [--qos=0] <topic> <msg>",
    "publish 发布": "publish [--qos=0] [--retain=false] <topic>",
    "exit 退出": "exit"
}
CMD_OPTS = ["PRESS ENTER 回车", "subscribe 订阅  ", "publish 发布    ", "config 配置     ", "exit 退出       "]

# SHOW = dynamically generated

SHOW_ITEMS = [
    "Broker Address",
    "Broker Port   ",
    "Login Name    ",
    "Login Password",
    "Default Topics",
    "Default Qos   ",
    "Debug         "
]

DICTIONARYS = {
    "cn": {
        "Runtime error: %s": "运行时发生错误: %s",
        ": debug is True": ": 调试开关(开)",
        ": debug is False": ": 调试开关(关)",
        "debug=True": "调试开关(开)",
        "debug=False": "调试开关(关)",

        "Connected successfully%s": "连接成功%s",
        "Connected failed: %s": "连接失败: %s",

        "Subscribed successfully: topic=%s | qos=%s": "订阅成功: topic=%s | qos=%s",
        "Subscribing failed: %s": "订阅失败: %s",

        "UnSubscribed successfully: topic=%s": "退订成功: topic=%s",
        "UnSubscribing topic %s failed: %s": "退订主题 %s 失败: %s",

        "Published successfully: topic={topic} | qos={qos} | retain={retain}\n[  SENT  ] msg=\n{msg}":
            "发布成功: topic={topic} | qos={qos} | retain={retain}\n[  SENT  ] msg=\n{msg}",
        "Publishing failed: %s": "发布失败: %s",

        "Putting queue failed: %s": "加入队列出错: %s",
        "Unpacking error: %s\n%s": "解包出错: %s\n%s",
        "Please check if your debug setting (True) suits for other mqtt clients": "请确认其它 mqtt客户端 是否兼容调试开关(开)",
        "Please check if your debug setting (False) suits for other mqtt clients": "请确认其它 mqtt客户端 是否兼容调试开关(关)",

        "go to edit your command": "进入编辑命令模式",
        "Press Enter to edit your command": "回车以编辑命令",
        "\tAnywhere you can type %s to cancel current operation": "\t任何地方鍵入取消符 %s 都可以取消当时操作",
        "Operation cancelled": "操作已取消",
        "Command submitted. PRESS ENTER to reenter the EDIT MODE": "命令已提交. 回车再次进入编辑模式",
        "EDIT MODE (PRESS ENTER to confirm your command or exit EDIT MODE back to display receiving msg)":
            "编辑模式 (回车以确认命令, 或退出编辑模式)",
        "disconnected": "连接断开",
        "waiting for reconnecting ...": "等待重连...",
        "goodbye": "再见"
    },
    "en": {}
}

DICTIONARY = DICTIONARYS[LANG]


def _(text):
    return DICTIONARY.get(text, text)


class KeyboardDisabler():
    def __init__(self):
        self.on = False

    def getwch_loop(self):
        import msvcrt
        while self.on:
            msvcrt.getwch()

    def start(self):
        self.on = True
        threading.Thread(target=self.getwch_loop).start()

    def stop(self):
        self.on = False

# todo for linux
keyboard_disabler = KeyboardDisabler()


class MQTTClientAssistant:

    def __init__(self):
        self.client = None
        self.queue = None
        self.stop = False
        self.exit = False
        self.debug = DEBUG
        self.inputting = False
        self.subscribed_topics = []

    def start(self):
        self.debug = DEBUG
        self.start_mqtt_client()

    def start_mqtt_client(self):
        client = self.create_client()
        client.connect(ADDR, PORT, 60)
        try:
            client.loop_forever()
        except Exception as E:
            self.on_error(_("Runtime error: %s") % E)

    def create_client(self):
        client = mqttc.Client()
        client.on_connect = self.on_connect_to_mqtt_broker
        client.on_message = self.on_message_from_mqtt_broker
        client.on_disconnect = self.on_disconnect_from_mqtt_broker
        client.username_pw_set(username=USERNAME, password=PASSWORD or None)
        return client

    def on_connect_to_mqtt_broker(self, client, userdata, flags, rc):
        if rc == 0:
            self.stop = False
            # keyboard_disabler.stop()

            self.on_info(_("Connected successfully%s") % _(": debug is %s" % self.debug))
            self.client = client
            self.queue = Queue()

            default_topics = DEFAULT_TOPICS.split(",")
            for default_topic in default_topics:
                client.subscribe(default_topic)
                try:
                    self.client.subscribe(default_topic, DEFAULT_TOPICS_QOS)
                    self.on_info(_("Subscribed successfully: topic=%s | qos=%s") % (default_topic, DEFAULT_TOPICS_QOS))
                except Exception as E:
                    self.on_error(_("Subscribing failed: %s") % E)

            threading.Thread(target=self.start_mqtt_cmder).start()
            threading.Thread(target=self.start_mqtt_recver).start()
        else:
            self.on_error(_("Connected failed: %s") % connack_string(rc))

    def on_message_from_mqtt_broker(self, client, userdata, msg):
        msg_byte_packed = msg.payload
        try:
            msg_unpacked = self.unpackb_msg(msg_byte_packed)
        except Exception as E:
            msg_unpacked = msg_byte_packed
            unpacking_error = _("Unpacking error: %s\n%s") % (E, msg_byte_packed)
            please_check = _("Please check if your debug setting (%s) suits for other mqtt clients" % self.debug)
            if self.inputting:
                self.queue.put({"error": unpacking_error})
                self.queue.put({"error": please_check})
            else:
                self.on_error(unpacking_error)
                self.on_error(please_check)
        try:
            self.queue.put({"payload": msg_unpacked})
        except Exception as E:
            self.on_error(_("Putting queue failed: %s") % E)

    def on_disconnect_from_mqtt_broker(self, client, userdata, rc):
        self.stop = True
        if not self.exit:
            print(_("disconnected"))
        for topic in self.subscribed_topics:
            self.client.unsubscribe(topic)
        self.client.disconnect()

    def start_mqtt_cmder(self):
        global DEBUG
        while not self.stop:

            cmd = "".join(list(self.multi_input())) if self.inputting else input()

            if self.stop:
                # print(_("waiting for reconnecting ..."))
                break

            cmd_matched_input = re.match(r"^\s*$", cmd)
            if cmd_matched_input:
                if self.inputting:
                    self.on_info(_("Command submitted. PRESS ENTER to reenter the EDIT MODE"))
                else:
                    self.on_info(_("EDIT MODE (PRESS ENTER to confirm your command or exit EDIT MODE back to display receiving msg)"))
                self.inputting = not self.inputting
                continue

            cmd_matched_exit = re.match(r"^\s*exit\s*$", cmd)
            if cmd_matched_exit:
                self.stop = self.exit = True
                for topic in self.subscribed_topics:
                    self.client.unsubscribe(topic)
                self.client.disconnect()
                print(_("goodbye"))
                break

            cmd_matched_help = re.match(r"^\s*(\w+)\s*$", cmd)
            if cmd_matched_help:
                cmd_to_help = cmd_matched_help.groups()[0].lower()
                if cmd_to_help == "help":
                    for cmd_opt in CMD_OPTS:
                        print("\t{cmd}:\t{help}"
                              .format(cmd=cmd_opt,
                                      help=HELP.get(re.sub(r"\s*$", "", cmd_opt))))
                    print(_("\tAnywhere you can type %s to cancel current operation") % CANCEL_CHAR.replace("\s*", ""))
                    # self.inputting = False
                    continue
                elif cmd_to_help == "show":
                    SHOW = {
                        "Broker Address": ADDR,
                        "Broker Port": PORT,
                        "Login Name": USERNAME or "N.A.",
                        "Login Password": "******",
                        "Default Topics": DEFAULT_TOPICS,
                        "Default Qos": DEFAULT_TOPICS_QOS,
                        "Debug": DEBUG 
                    }
                    for item in SHOW_ITEMS:
                        print("\t{config}:\t{setting}"
                                  .format(config=item,
                                          setting=SHOW.get(re.sub(r"\s*$", "", item))))
                    continue
                else:
                    print("\t{cmd}:\t{help}".format(cmd=cmd_to_help, help=HELP.get(cmd_to_help.replace(" ", "")) or "Invalid command"))
                    print(_("\tAnywhere you can type %s to cancel current operation") % CANCEL_CHAR.replace("\s*", ""))
                    # self.inputting = False
                    continue

            # 分界线
            if not self.inputting:
                self.on_info(_("Press Enter to edit your command"))
                continue
            # 分界线

            cmd_matched_cancel = re.search(r"%s$" % CANCEL_CHAR, cmd)
            if cmd_matched_cancel:
                self.on_info(_("Operation cancelled"))
                # self.inputting = False  # 继续留在 EDIT MODE
                continue

            cmd_matched_config = re.match(r"\s*config((?:\s+--[^=]+\s*=\w+)*)", cmd)
            if cmd_matched_config:
                params = cmd_matched_config.groups()[0]
                debug = self.get_param(params, "debug", False)
                self.debug = debug
                self.on_info(_("debug=%s" % debug))
                self.inputting = False
                DEBUG = debug
                continue

            cmd_matched_subscribe = re.match(r"\s*subscribe\s+((?:\s+--[^=]+\s*=\w+)*)[\s\n]*(.*)", cmd)
            if cmd_matched_subscribe:
                params, topic = cmd_matched_subscribe.groups()
                qos = self.get_param(params, "qos", default=0)
                try:
                    self.client.subscribe(topic, qos)
                    self.subscribed_topics.append(topic)
                    self.on_info(_("Subscribed successfully: topic=%s | qos=%s") % (topic, qos))
                except Exception as E:
                    self.on_error(_("Subscribing failed: %s") % E)
                self.inputting = False
                continue

            cmd_matched_publish = re.match(r"\s*publish\s+((?:--[^=]+\s*=\w+\s+)*)([^\n\s]+)[\n\s]+(.*)", cmd)
            if cmd_matched_publish:
                params, topic, msg = cmd_matched_publish.groups()
                qos = self.get_param(params, "qos", default=0)
                retain = self.get_param(params, "retain", default=False)
                try:
                    packed_msg = self.packb_msg(msg)
                    self.client.publish(topic, packed_msg, qos, retain)
                    self.on_info(_("Published successfully: topic={topic} | qos={qos} | retain={retain}\n[  SENT  ] msg=\n{msg}").format(
                        topic=topic, qos=qos, retain=retain, msg=json.dumps(json.loads(msg.replace("'", '"')), indent=4)))
                except Exception as E:
                    self.on_error(_("Publishing failed: %s") % E)
                self.inputting = False
                continue

            cmd_matched_unsubscribe = re.match(r"\s*unsubscribe[\s\n]*(.*)", cmd)
            if cmd_matched_unsubscribe:
                topic = cmd_matched_unsubscribe.groups()[0]
                try:
                    self.client.unsubscribe(topic)
                    self.subscribed_topics.pop(self.subscribed_topics.index(topic))
                    self.on_info(_("UnSubscribed successfully: topic=%s") % topic)
                except Exception as E:
                    self.on_error(_("UnSubscribing topic %s failed: %s") % (topic, E))
                self.inputting = False
                continue

            self.on_error(_("Invalid command"))
            self.inputting = False

        # keyboard_disabler.start()

    def start_mqtt_recver(self):
        while not self.stop:
            if self.queue.empty() or self.inputting:
                continue
            msg = self.queue.get()
            pld = msg.get("payload")
            error = msg.get("error")
            if error:
                self.on_error(error)
            else:
                try:
                    self.on_info("\n%s" % json.dumps(pld, indent=4), topic="RECEIVED")
                except:
                    self.on_info("\n%s" % pld, topic="RECEIVED")

    def multi_input(self, prompt=">"):
        try:
            while not self.stop:
                data = input(prompt)
                if not data: break
                yield data
        except KeyboardInterrupt:
            return

    @staticmethod
    def get_param(params, name, default=None):
        """
        note: if name not found in params then return default
        """
        if not params:
            return default
        param = default
        matched = re.search(r"--%s=\s*([^\s]+)" % name, params)
        if matched:
            param = matched.groups()[0]
        try:
            if str(param).lower() == "true":
                return True
            elif str(param).lower() == "false":
                return False
        except:
            pass
        try:
            param = int(param)
        except:
            pass
        return param

    def packb_msg(self, msg):  # pack a msg which is dict type to string for transmission
        """
          variables: msg → msg_str → msg_byte(available for transmission)
        type of var: obj →   str   →   byte
            methods:    dumps   encode
        :param msg:
        :return:
        """
        # try:
        #     msg_str = json.dumps(msg)  # json object -> json string
        # except ValueError:
        #     pass
        msg_str = msg.replace("'", '"')
        if self.debug:
            msg_byte_packed = msg_str.encode()  # string -> byte
        else:
            msg_byte = msg_str.encode()
            msg_byte_packed = msgpack.packb(msg_byte)  # byte -> packed byte

        return msg_byte_packed

    def unpackb_msg(self, msg_byte_packed):  # unpack a msg which is string type to dict/obj for application
        """
          variables: msg → msg_str → msg_obj(available for applications)
        type of var: byt →   str   →   obj
            methods:    loads   decode
        :param msg:
        :return:
        """
        if self.debug:  # msg = byte like b'{"x": 0, "y": 0, "z": 0}'
            msg_str = msg_byte_packed.decode()  # json byte -> json string '{"x": 0, "y": 0, "z": 0}'
        else:  # msg = packed byte
            msg_byte = msgpack.unpackb(msg_byte_packed)  # packed byte -> unpacked byte
            msg_str = msg_byte.decode()  # unpacked byte -> string
        try:
            msg = json.loads(msg_str)  # json string -> json object
        except ValueError:
            msg = msg_str
        return msg

    @staticmethod
    def get_time(format="%Y-%m-%d %H:%M:%S"):
        return time.strftime(format, time.localtime(time.time()))

    def on_info(self, info, topic="INFO"):
        print("[  %s %s  ] %s" % (topic, self.get_time(), info))

    def on_error(self, error, topic="ERROR"):
        print("[  %s %s  ] %s" % (topic, self.get_time(), error))

if __name__ == "__main__":
    if len(sys.argv) == 1:
        assistant = MQTTClientAssistant()
        assistant.start()
    elif sys.argv[1] == "help":
        print("\n\tInstructions for optional parameters\n"
              "\n\t--addr=<mqtt broker ip address>\n\t  └default is {ADDR}\n"
              "\n\t--port=<mqtt broker port>\n\t  └default is {PORT}\n"
              "\n\t--username=<username>\n\t  └default is {USERNAME}\n"
              "\n\t--password=<password>\n\t  └default is {PASSWORD}\n"
              "\n\t--default_topics=<default topics will be subscribed on connected>\n\t  └default is {DEFAULT_TOPICS}\n"
              "\n\t--default_topics_qos=<qos for above default topics>\n\t  └default is {DEFAULT_TOPICS_QOS}\n"
              "\n\t--cancel_char=<a (series of) character for cancelling operation>\n\t  └default is {CANCEL_CHAR}\n"
              "\n\t--debug=<true or false to switch on/off debug>\n\t  └default is {DEBUG}\n"
              "\n\t--lang=<cn or en>\n\t  └default is {LANG}\n"
              .format(ADDR=ADDR, PORT=PORT,
                      USERNAME=USERNAME or "empty", PASSWORD=PASSWORD or "empty",
                      DEFAULT_TOPICS=DEFAULT_TOPICS,
                      DEFAULT_TOPICS_QOS=DEFAULT_TOPICS_QOS,
                      CANCEL_CHAR=CANCEL_CHAR.replace("\s*", ""),
                      DEBUG=DEBUG, LANG=LANG))
        print("\n\t可选参数说明\n"
              "\n\t--addr=<mqtt broker ip 地址>\n\t  └默认为 {ADDR}\n"
              "\n\t--port=<mqtt broker 端口>\n\t  └默认为 {PORT}\n"
              "\n\t--username=<用户名>\n\t  └默认为 {USERNAME}\n"
              "\n\t--password=<密码>\n\t  └默认为 {PASSWORD}\n"
              "\n\t--default_topics=<连接后默认订阅的主题>\n\t  └默认为 {DEFAULT_TOPICS}\n"
              "\n\t--default_topics_qos=<上述主题的 qos值>\n\t  └默认为 {DEFAULT_TOPICS_QOS}\n"
              "\n\t--cancel_char=<取消符字符(串)>\n\t  └默认为 {CANCEL_CHAR}\n"
              "\n\t--debug=<true 或 false 对应调试开或关>\n\t  └默认为 {DEBUG}\n"
              "\n\t--lang=<cn 或 en 对应中文或英文>\n\t  └默认为 {LANG}\n"
              .format(ADDR=ADDR, PORT=PORT,
                      USERNAME=USERNAME or "empty", PASSWORD=PASSWORD or "empty",
                      DEFAULT_TOPICS=DEFAULT_TOPICS,
                      DEFAULT_TOPICS_QOS=DEFAULT_TOPICS_QOS,
                      CANCEL_CHAR=CANCEL_CHAR.replace("\s*", ""),
                      DEBUG=DEBUG, LANG=LANG))
    else:
        params = " ".join(sys.argv[1:])
        assistant = MQTTClientAssistant()
        ADDR = assistant.get_param(params, "addr", ADDR)
        PORT = assistant.get_param(params, "port", PORT)
        USERNAME = assistant.get_param(params, "username", USERNAME)
        PASSWORD = assistant.get_param(params, "password", PASSWORD)
        DEFAULT_TOPICS = assistant.get_param(params, "default_topics", DEFAULT_TOPICS)
        DEFAULT_TOPICS_QOS = assistant.get_param(params, "default_topics_qos", DEFAULT_TOPICS_QOS)
        CANCEL_CHAR = str(assistant.get_param(params, "cancel_char", CANCEL_CHAR))
        DEBUG = assistant.get_param(params, "debug", DEBUG)
        LANG = assistant.get_param(params, "lang", LANG)
        DICTIONARY = DICTIONARYS.get(LANG)
        assistant.start()
