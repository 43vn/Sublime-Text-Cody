import sublime
import sublime_plugin

import json
import requests
import threading
class CodyCommand(sublime_plugin.TextCommand):
    def check_api(self):
        settings = sublime.load_settings('cody.sublime-settings')
        key = settings.get('api_key', None)
        if key is None:
            msg = "Đặt access tokens vào 'api_key' in the CodyAI trong cài đặt"
            sublime.status_message(msg)
            raise ValueError(msg)
    def check_setup(self):
        self.check_api()
        if len(self.view.sel()) > 1:
            msg = "Vui lòng bôi đen 1 đoạn code."
            sublime.status_message(msg)
            raise ValueError(msg)

        region = self.view.sel()[0]
        if region.empty():
            msg = "Vui lòng bôi đen vùng code."
            sublime.status_message(msg)
            raise ValueError(msg)

    def handle_thread(self, thread, seconds=0):
        settings = sublime.load_settings('cody.sublime-settings')
        max_seconds = settings.get('max_seconds', 60)

        if seconds > max_seconds:
            msg = "Cody ran out of time! {}s".format(max_seconds)
            sublime.status_message(msg)
            return

        if thread.running:
            msg = "Đang đợi Cody. Vui lòng chờ... ({}/{}s)".format(
                seconds, max_seconds)
            sublime.status_message(msg)
            # Wait a second, then check on it again
            sublime.set_timeout(lambda:
                self.handle_thread(thread, seconds + 1), 1000)
            return

        if not thread.result:
            #sublime.status_message("Something is wrong with Cody - aborting")
            return

        self.view.run_command('replace_text', {
            "region": [thread.region.begin(),thread.region.end()],
            "text": thread.preText + "\n" + thread.result
        })

    def handle_model_thread(self, thread, seconds=0):
        settings = sublime.load_settings('cody.sublime-settings')
        max_seconds = settings.get('max_seconds', 60)

        if seconds > max_seconds:
            msg = "Cody chạy quá thời gian quy định {}s".format(max_seconds)
            sublime.status_message(msg)
            return

        if thread.running:
            msg = "Đang lấy danh sách model của CodyAI. ({}/{}s)".format(
                seconds, max_seconds)
            sublime.status_message(msg)
            sublime.set_timeout(lambda:
                self.handle_model_thread(thread, seconds + 1), 1000)
            return

        if not thread.result:
            #sublime.status_message("Something is wrong with Cody - aborting")
            return
        items = thread.result
        def on_done(index):
            if index != -1:
                selected_text = items[index]
                sublime.set_clipboard(selected_text)
                sublime.status_message("📋 Copied: {}".format(selected_text))
        window = self.view.window()
        window.show_quick_panel(items, on_done)

class CodyGenCommand(CodyCommand):
    def run(self, edit):
        self.check_setup()
        region = self.view.sel()[0]
        settings = sublime.load_settings('cody.sublime-settings')
        settingsc = settings.get('completions')
        user_prompt = self.view.substr(region)
        hasPreText = settingsc.get('keep_prompt_text')
        preText = user_prompt if hasPreText else ""
        data = {
            'model': settingsc.get('model', "anthropic::2024-10-22::claude-3-7-sonnet-latest"),
            'messages': [
                {"role": "assistant", "content": settingsc.get('prompt', "You are a senior DevOps engineer. Respond with only the required shell script, server configuration, or code block. Do not include any markdown syntax, explanations, or conversational text. Also, do not add any leading or trailing blank lines.")},
                {"role": "user", "content": user_prompt}
            ],
            'temperature': settingsc.get('temperature', 0.5),
            "max_tokens": settings.get('max_tokens', 32000)
        }
        thread = AsyncCody(region, 'chat/completions', data, preText)

        thread.start()
        self.handle_thread(thread)

class CodyGetModelCommand(CodyCommand):
    def run(self, edit):
        self.check_api()
        thread = AsyncCodyModel()
        thread.start()
        self.handle_model_thread(thread)


class CodyEditCommand(CodyCommand):
    def input(self, args):
        return InstructionInputHandler()

    def run(self, edit, instruction):
        self.check_setup()
        settings = sublime.load_settings('cody.sublime-settings')
        settingse = settings.get('edits')
        region = self.view.sel()[0]
        messages = [
            {"role": "assistant", "content": settingse.get('prompt', "You are a senior DevOps engineer. Refactor or edit code/config as requested. Respond with code only — no markdown, no explanation, no chat.")},
            {"role": "user", "content": "{}\n\n{}".format(instruction, selected_code)}
        ]
        data = {
            'model': settingse.get('edit_model', "anthropic::2024-10-22::claude-3-7-sonnet-latest"),
            'messages': messages,
            'temperature': settingse.get('temperature', 0.3),
            "max_tokens": settings.get('max_tokens', 32000)
        }
        thread = AsyncCody(region, 'chat/completions', data, "")
        thread.start()
        self.handle_thread(thread)


class InstructionInputHandler(sublime_plugin.TextInputHandler):
    def name(self):
        return "instruction"

    def placeholder(self):
        return "E.g.: 'translate to java' or 'add documentation'"

class AsyncCodyModel(threading.Thread):
    def __init__(self):
        super().__init__()
        self.result = None
        self.running = False

    def run(self):
        self.running = True
        try:
            self.result = self.get_cody_response()
        except Exception as e:
            sublime.status_message("Cody error: {}".format(e))
            self.result = None
        finally:
            self.running = False

    def get_cody_response(self):
        models = []
        settings = sublime.load_settings('cody.sublime-settings')
        api_key = settings.get('api_key')
        url = "https://sourcegraph.com/.api/llm/models"
        headers = {
            "Authorization": "token {}".format(api_key),
            "Content-Type": "application/json",
            "User-Agent": "cody-sublime-text 1.0",
            "X-Requested-With": "cody-sublime-text 1.0",
            "Accept": "*/*"
        }

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            resp_json = response.json()
        except requests.exceptions.RequestException as e:
            raise Exception("Request error: {}".format(e))

        if 'error' in resp_json:
            print("API error: {}".format(resp_json['error']['message']))
            raise Exception("API error: {}".format(resp_json['error']['message']))
        data = resp_json.get('data', [{}])
        for item in data:
            model_id = item.get('id')
            if model_id:
                models.append(model_id)
        sublime.status_message("✅ Đã tải danh sách model từ CodyAI. Để copy tên model click vào tên model")
        return models

class AsyncCody(threading.Thread):
    def __init__(self, region, endpoint, data, preText):
        super().__init__()
        self.region = region
        self.endpoint = endpoint
        self.data = data
        self.preText = preText
        self.result = None
        self.running = False

    def run(self):
        self.running = True
        try:
            self.result = self.get_cody_response()
        except Exception as e:
            sublime.status_message("Cody error: {}".format(e))
            self.result = None
        finally:
            self.running = False

    def get_cody_response(self):
        settings = sublime.load_settings('cody.sublime-settings')
        api_key = settings.get('api_key')
        url = "https://sourcegraph.com/.api/llm/{}".format(self.endpoint)
        headers = {
            "Authorization": "token {}".format(api_key),
            "Content-Type": "application/json",
            "User-Agent": "cody-sublime-text 1.0",
            "X-Requested-With": "cody-sublime-text 1.0",
            "Accept": "*/*"
        }

        try:
            response = requests.post(url, headers=headers, json=self.data)
            response.raise_for_status()
            resp_json = response.json()
        except requests.exceptions.RequestException as e:
            raise Exception("Request error: {}".format(e))

        if 'error' in resp_json:
            print("API error: {}".format(resp_json['error']['message']))
            raise Exception("API error: {}".format(resp_json['error']['message']))
        choice = resp_json.get('choices', [{}])[0]
        message = choice.get('message', "")
        text = message.get('content', "")
        usage = resp_json.get('usage', {}).get('total_tokens')

        if usage:
            sublime.status_message("✅ [CodyAI] Hoàn tất. Tokens: {}".format(usage))
        else:
            sublime.status_message("✅ [CodyAI] Hoàn tất")
        return text



class ReplaceTextCommand(sublime_plugin.TextCommand):
    def run(self, edit, region, text):
        region = sublime.Region(*region)
        self.view.replace(edit, region, text)
