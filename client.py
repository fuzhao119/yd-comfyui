import os
import json
import shutil
import logging
import requests
import subprocess
import time
from pathlib import Path
from tqdm import tqdm

logging.basicConfig(level=logging.INFO)

class HotUpdater:
    def __init__(self):
        self.config = self.load_config()
        self.client_root = Path('.').resolve()
        self.temp_dir = None
        self.local_snapshot, self.local_version = self.load_local_snapshot()

    def load_local_snapshot(self):
        snapshot_path = self.client_root / 'UpdateConfiguration.xml'
        if not snapshot_path.exists():
            return {}, 0
        try:
            with open(snapshot_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                version = int(data.get('version', 0))
                logging.info(f"版本号: {version}")
                return data.get('files', {}), version
        except Exception as e:
            logging.error(f"本地快照加载失败: {str(e)}")
            return {}, 0

    def load_config(self):
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_with_retry(self, url, max_retries=3, delay=2):
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.get(url, timeout=15)
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                if attempt < max_retries:
                    time.sleep(delay)
                else:
                    logging.error(f"连接服务器失败（重试 {max_retries} 次后放弃）: {e}")
                    return None

    def check_version(self):
        url = f"{self.config['server_url']}/version"
        response = self.get_with_retry(url)
        if response is None:
            return False, None
        try:
            logging.debug(f"服务器响应内容: {response.text}")
            return True, response.json()
        except json.JSONDecodeError as json_err:
            logging.error(f"服务器响应不是有效 JSON: {json_err}")
            logging.debug(f"原始响应内容: {response.text}")
            return False, None

    def needs_update(self, server_data):
        return server_data['version'] > self.local_version

    def apply_changes(self, server_data):
        try:
            self.temp_dir = self.client_root / "temp_update"
            self.temp_dir.mkdir(exist_ok=True)
            updated_files = []
            for path, server_meta in server_data['files'].items():
                status = server_meta.get('status')
                local_value = self.local_snapshot.get(path, {}).get('value', 0)
                server_value = server_meta.get('value', 0)

                if status == 'empty_folder':
                    target_dir = self.client_root / path
                    target_dir.mkdir(parents=True, exist_ok=True)
                elif status == 'add':
                    if self.download_file(path):
                        updated_files.append(path)
                elif status == 'updated' and server_value > local_value:
                    if self.download_file(path):
                        updated_files.append(path)
                elif status == 'delete':
                    target_path = self.client_root / path
                    if target_path.is_file():
                        target_path.unlink()
                    elif target_path.is_dir():
                        shutil.rmtree(target_path)

            for item in self.temp_dir.rglob('*'):
                if item.is_file():
                    rel_path = item.relative_to(self.temp_dir)
                    target = self.client_root / rel_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(item), str(target))

            self.local_snapshot.update(server_data['files'])
            with open('UpdateConfiguration.xml', 'w', encoding='utf-8') as f:
                json.dump({
                    "version": server_data['version'],
                    "files": self.local_snapshot
                }, f, indent=2, ensure_ascii=False)

            return True
        except Exception as e:
            logging.error(f"更新失败: {str(e)}")
            return False
        finally:
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir)

    def run_update(self):
        connected, server_data = self.check_version()
        if not connected:
            logging.info("无法连接服务器，跳过更新")
            self.execute_callback()
            return False

        if not self.needs_update(server_data):
            logging.info("当前已是最新版本")
            self.execute_callback()
            return True

        logging.info(f"发现新版本 v{server_data['version']}")
        if self.apply_changes(server_data):
            logging.info("更新成功!")
            self.execute_callback()
            return True
        else:
            logging.error("更新失败")
            self.execute_callback()
            return False

    def execute_callback(self):
        callback_path = Path(self.config['callback_path'])
        if not callback_path.is_absolute():
            callback_path = self.client_root / callback_path

        if callback_path.exists():
            try:
                logging.info(f"正在执行回调脚本: {callback_path}")
                if os.name == 'nt':
                    subprocess.run(str(callback_path), shell=True)
                else:
                    os.chmod(str(callback_path), 0o755)
                    subprocess.run([str(callback_path)], shell=False)
            except Exception as e:
                logging.error(f"执行回调脚本失败: {str(e)}")
        else:
            logging.warning(f"回调脚本不存在: {callback_path}")

    def download_file(self, rel_path):
        try:
            rel_path = rel_path.replace("\\", "/")
            target_path = self.temp_dir / rel_path
            target_path.parent.mkdir(parents=True, exist_ok=True)

            response = requests.get(f"{self.config['server_url']}/download/{rel_path}", stream=True)
            if response.status_code == 200:
                total_size = int(response.headers.get('Content-Length', 0))
                with open(target_path, 'wb') as f, tqdm(
                    desc=f"下载 {rel_path}",
                    total=total_size,
                    unit='B',
                    unit_scale=True,
                    ncols=100
                ) as pbar:
                    for chunk in response.iter_content(chunk_size=1024):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))
                return True
            return False
        except Exception as e:
            logging.error(f"文件下载失败 {rel_path}: {str(e)}")
            return False

if __name__ == '__main__':
    updater = HotUpdater()
    updater.run_update()
