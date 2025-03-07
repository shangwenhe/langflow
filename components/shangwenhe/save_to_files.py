import json
import os
import unicodedata

from langflow.custom import Component
from langflow.inputs import BoolInput, MessageTextInput
from langflow.schema.message import Message
from langflow.template import Output


class SaveFilesComponent(Component):
    display_name = "Save to Files"
    description = "将输出的JSON格式存在到文件中"
    icon = "save"
    name = "SaveToFile"

    inputs = [
        MessageTextInput(
            name="json_str", display_name="JSON String", info="The JSON string to be cleaned.", required=True
        ),
        BoolInput(
            name="remove_control_chars",
            display_name="Remove Control Characters",
            info="Remove control characters from the JSON string.",
            required=False,
        ),
        BoolInput(
            name="normalize_unicode",
            display_name="Normalize Unicode",
            info="Normalize Unicode characters in the JSON string.",
            required=False,
        ),
        BoolInput(
            name="validate_json",
            display_name="Validate JSON",
            info="Validate the JSON string to ensure it is well-formed.",
            required=False,
        ),
    ]

    outputs = [
        Output(display_name="Cleaned JSON String", name="output", method="clean_json"),
    ]

    def clean_json(self) -> Message:
        try:
            from json_repair import repair_json
        except ImportError as e:
            msg = "Could not import the json_repair package. Please install it with `pip install json_repair`."
            raise ImportError(msg) from e

        """Clean the input JSON string based on provided options and return the cleaned JSON string."""
        json_str = self.json_str
        remove_control_chars = self.remove_control_chars
        normalize_unicode = self.normalize_unicode
        validate_json = self.validate_json

        start = json_str.find("{")
        end = json_str.rfind("}")
        if start == -1 or end == -1:
            msg = "Invalid JSON string: Missing '{' or '}'"
            raise ValueError(msg)
        try:
            json_str = json_str[start : end + 1]

            if remove_control_chars:
                json_str = self._remove_control_characters(json_str)
            if normalize_unicode:
                json_str = self._normalize_unicode(json_str)
            if validate_json:
                json_str = self._validate_json(json_str)

            cleaned_json_str = repair_json(json_str)
            result = str(cleaned_json_str)
            
            data = json.loads(result)
            print(data)
            # self._save_files(data)
            
            
            # 指定保存文件的目录
            base_dir = '/app/data/components/'
            # 确保目录存在，如果不存在则创建
            os.makedirs(base_dir, exist_ok=True)
        
            for item in data.get('files'):
                # 获取文件名
                file_path = item.get('file')
                # 获取文件内容
                content = item.get('content')
        
                if file_path and content:
                    # 提取文件名
                    file_name = os.path.basename(file_path)
                    # 提取文件路径中的目录部分
                    relative_dir = os.path.dirname(file_path)
                    # 拼接完整的保存目录
                    save_dir = os.path.join(base_dir, relative_dir.strip('./'))
                    # 确保保存目录存在，如果不存在则创建
                    os.makedirs(save_dir, exist_ok=True)
                    # 拼接完整的文件保存路径
                    full_path = os.path.join(save_dir, file_name)
        
                    try:
                        with open(full_path, 'w', encoding='utf-8') as file:
                            file.write(content)
                        print(f"成功保存文件: {full_path}")
                    except Exception as e:
                        print(f"保存文件 {full_path} 时出错: {e}")
            
            
            
            

            self.status = result
            return Message(text=result)
        except Exception as e:
            msg = f"Error cleaning JSON string: {e}"
            raise ValueError(msg) from e

    def _save_files(data):
        # 指定保存文件的目录
        base_dir = '/app/data/components/'
        # 确保目录存在，如果不存在则创建
        os.makedirs(base_dir, exist_ok=True)
    
        for item in data:
            # 获取文件名
            file_path = item.get('file')
            # 获取文件内容
            content = item.get('content')
    
            if file_path and content:
                # 拼接完整的文件路径
                full_path = os.path.join(base_dir, os.path.basename(file_path))
                try:
                    # 以写入模式打开文件
                    with open(full_path, 'w', encoding='utf-8') as file:
                        # 将内容写入文件
                        file.write(content)
                    print(f"成功保存文件: {full_path}")
                except Exception as e:
                    print(f"保存文件 {full_path} 时出错: {e}")

    def _remove_control_characters(self, s: str) -> str:
        """Remove control characters from the string."""
        return s.translate(self.translation_table)

    def _normalize_unicode(self, s: str) -> str:
        """Normalize Unicode characters in the string."""
        return unicodedata.normalize("NFC", s)

    def _validate_json(self, s: str) -> str:
        """Validate the JSON string."""
        try:
            json.loads(s)
        except json.JSONDecodeError as e:
            msg = f"Invalid JSON string: {e}"
            raise ValueError(msg) from e
        return s

    def __init__(self, *args, **kwargs):
        # Create a translation table that maps control characters to None
        super().__init__(*args, **kwargs)
        self.translation_table = str.maketrans("", "", "".join(chr(i) for i in range(32)) + chr(127))
