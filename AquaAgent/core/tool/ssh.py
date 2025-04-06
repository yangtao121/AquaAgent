import paramiko
from pathlib import Path
import logging
import time
import re
from typing import ClassVar, List

from langchain_core.tools import BaseTool
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field
from langchain_core.messages import ToolMessage


class SSHToolInput(BaseModel):
    command: str = Field(description="Bash commands to be executed on the user's computer")
    reset_ssh: bool = Field(description="Use this flag to create a new terminal, it can solve the problem that the terminal is stuck.", default=False)
    # tail_lines: int = Field(description="Number of lines to return from the end of output (0 means return all)", default=0)
    # 移除新增参数，优化将在内部默认实现


class SSHTool(BaseTool):
    name: str = "SSH"
    description: str = "Execute terminal commands on the user's computer using this tool."
    args_schema: ArgsSchema = SSHToolInput
    return_direct: bool = False
    
    # 默认的shell提示符匹配模式
    DEFAULT_PROMPT_PATTERNS: ClassVar[List[str]] = [
        # Docker中Anaconda环境的特殊匹配
        r'\([^)]+\) developer@[^:]+:[^\$]+\$\s*$',  # 精确匹配(base) developer@110dce07d505:~/code$
        r'\(base\) [^\s@]+@[^:]+:[^$]+\$\s*$',      # 精确匹配(base)开头的提示符
        # 匹配各种可能的提示符格式，从最特殊到最一般
        r'\r?\n\([^)]+\)\s+[^\s@]+@[^\s:]+:[^\s]+[#\$]\s*$',  # (env) username@hostname:path$
        r'\r?\n[^\s@]+@[^\s:]+:[^\s]+[#\$]\s*$',  # username@hostname:path$
        r'\r?\n\[[^\]]+\][#\$]\s*$',            # [user@host dir]$
        r'\r?\n[#\$>]\s*$',                      # $ or # or >
        r'[#\$>]\s*$',                           # 末尾的简单提示符
        # 匹配ANSI转义序列
        r'\r?\n.*\x1b\[[0-9;]*[a-zA-Z].*[#\$>]\s*$',  # 包含ANSI转义序列的提示符
        # 完全通用的模式，最后的后备方案
        r'[^\n]*[#\$>]\s*$'                     # 任何以$/#/>结尾的行
        # apt-get 结束模式 - 通常是空行或只有提示符的行
        r'Reading package lists... Done\r?\n',    # apt-get update 常见结束标志
        r'Building dependency tree... Done\r?\n', # apt-get 操作常见结束标志
        r'Reading state information... Done\r?\n' # apt-get 操作常见结束标志
        # 绝对通用的模式 - 移除，因为太容易误匹配
        # r'\n[^\n]{0,40}$'                      # 任何行尾内容，限制长度防止误匹配
    ]
    
    # 需要排除的模式列表，匹配这些模式的提示符不会被视为命令完成
    EXCLUDE_PATTERNS: ClassVar[List[str]] = [
        r'.*password.*for.*:.*$',    # 排除密码提示符
        r'.*\[sudo\].*password.*:.*$',  # 排除sudo密码提示符
        r'.*Password:.*$',           # 排除简单的密码提示符
    ]
    
    # 添加用于检测分页器的模式
    PAGER_PATTERNS: ClassVar[List[str]] = [
        r'--More--($|\r?\n)',
        r'--More--.*?($|\r?\n)',
        r'.*?--More--.*?($|\r?\n)',
        r'--More--\(\d+%\)($|\r?\n)',
        r'\(END\)($|\r?\n)',
        r'\(more\)($|\r?\n)',
        r'Press q to quit, any other key to continue',
        r'Press RETURN to continue'
    ]
    
    # 添加用于检测交互式提示的模式
    INTERACTIVE_PROMPT_PATTERNS: ClassVar[List[str]] = [
        r'Do you accept the license terms\?',
        r'(yes|no)(\s+)?$',
        r'(y/n)(\s+)?$',
        r'(\[Y/n\])(\s+)?$',
        r'(\[y/N\])(\s+)?$',
        r'Do you want to continue\?',
        r'(yes\|no)(\s+)?$',
        r'please answer (yes|no)',
        r'Press ENTER to continue',
        r'(?i)press any key to continue',
        r'(?i)please select an option',
        r'^\s*\[\s*\]\s+\w+',  # 选择菜单项
        r'Proceed \(\[y\]/n\)\?', # 匹配"Proceed ([y]/n)?"格式
        r'Proceed \(\[.*?\]\)(\s+)?$', # 更通用的Proceed提示匹配
        r'Do you wish to continue\?', # conda环境删除确认
        r'\(y/\[n\]\)\?', # conda环境删除确认格式
        r'.*will be deleted.*continue', # 通用删除确认提示
        r'Press \[ENTER\] to continue or Ctrl-c to cancel', # Ubuntu添加组件提示
        r'.*component.*to all repositories.*', # 通用组件添加提示
        r'.*Press.*to continue.*', # 非常通用的继续提示
        r'Waiting for cache lock:.*', # apt锁等待提示
        r'Could not get lock .*/var/lib/dpkg/lock.*', # dpkg锁提示
        r'Could not get lock .*/var/lib/apt/lists/lock.*', # apt lists锁提示
    ]
    
    # 添加用于检测下载进度条模式的正则表达式
    DOWNLOAD_PROGRESS_PATTERNS: ClassVar[List[str]] = [
        r'\|\s*\d+%',         # | 50%
        r'\d+%\s*\|',         # 50% |
        r'#+ *\| *\d+%',      # ########## | 50%
        r'\d+% *\| *#+',      # 50% | ##########
        r'\|\s*#+\s*\|\s*\d+%', # | ########## | 50%
        r'\d+%.*\[.*\]',      # 50% [======>      ]
        r'\[#+[>\s]*\]',      # [======>      ]
        r'Downloading.*\d+%',  # Downloading... 50%
        r'Progress.*\d+%',     # Progress: 50%
        r'Download.*\d+\/\d+', # Downloaded 50/100
        r'Installing.*\d+%',   # Installing... 50%
        r'\d+\.\d+ MB',        # 171.5 MB
        r'Downloading and Extracting Packages',  # Conda specific marker
        r'Preparing transaction',                # Conda specific marker
        r'Verifying transaction',                # Conda specific marker
        r'Executing transaction',                # Conda specific marker
        # Docker specific progress markers
        r'Downloading\s+\d+.*\/\d+.*[MKG]B',    # Docker layer download: Downloading 2.143MB/187.5MB
        r'[a-f0-9]+: Downloading',              # Docker layer ID: a9a9ebe7ac34: Downloading
        r'[a-f0-9]+: Pulling',                  # Docker layer pull indicator
        r'[a-f0-9]+: Waiting',                  # Docker layer waiting 
        r'[a-f0-9]+: Verifying',                # Docker layer verification
        r'[a-f0-9]+: Download complete',        # Docker layer download completion
        r'[a-f0-9]+: Extracting',               # Docker layer extraction
        r'[a-f0-9]+: Pull complete',            # Docker layer pull completion
        r'Pulling from',                        # Docker repository pull indicator
        # Git specific progress markers
        r'(remote:\s+)?Counting objects:',      # Git clone counting objects
        r'(remote:\s+)?Compressing objects:',   # Git clone compressing objects 
        r'(remote:\s+)?Receiving objects:',     # Git clone receiving objects
        r'(remote:\s+)?Resolving deltas:',      # Git clone resolving deltas
        r'remote: Finding sources',             # GitHub finding sources
        r'remote: Finding sources',             # GitHub finding sources
        r'Unpacking objects:',                  # Git clone unpacking objects
        r'Checking out files:'                  # Git checkout progress
    ]
    
    def __init__(self,
                 host: str,
                 username: str,
                 password: str,
                 port: int = 22,
                 timeout: int = 10,
                 debug_mode: bool = True,
                 ):
        
        super().__init__()
        self._host = host
        self._username = username
        self._password = password
        self._port = port
        self._timeout = timeout
        self._key_filename = None
        self._client = None
        self._sftp = None
        self._logger = logging.getLogger(__name__)
        self._channel = None
        self._interactive_mode = True
        self._debug_mode = debug_mode  # 添加调试模式标志
        
        self._pre_execute_command = []
        self._prompt_patterns = self.DEFAULT_PROMPT_PATTERNS.copy()
        self._exclude_patterns = self.EXCLUDE_PATTERNS.copy()
        self._pager_patterns = self.PAGER_PATTERNS.copy()
        self._interactive_prompt_patterns = self.INTERACTIVE_PROMPT_PATTERNS.copy()
        self._download_progress_patterns = self.DOWNLOAD_PROGRESS_PATTERNS.copy()
        
        self._known_prompts = [
                    "(base) developer@", 
                    "~/code$", 
                    "@110dce07d505:",
                    "root@",
                    # 添加常见的apt-get完成后可能出现的提示符
                    "]:~#",      # root用户家目录提示符
                    "]:/#",      # root用户根目录提示符
                    # 通用的基于用户名的提示符
                    "@ubuntu:",
                    "@debian:"
                ]
        
        self._known_prompts.append(username)
        
        # 用于debug日志输出的缓冲区
        self._debug_log_buffer = []
        self._max_debug_lines = 200
        
    def _limited_debug_log(self, message):
        """
        限制debug日志输出行数的辅助方法
        
        参数:
            message (str): 要记录的日志消息
        """
        # 按行分割
        lines = message.splitlines()
        
        # 如果行数超过最大限制，只保留头尾部分
        if len(lines) > self._max_debug_lines:
            head_lines = self._max_debug_lines // 2
            tail_lines = self._max_debug_lines - head_lines
            truncated_message = "\n".join(lines[:head_lines]) + f"\n... [截断 {len(lines) - self._max_debug_lines} 行] ...\n" + "\n".join(lines[-tail_lines:])
            self._logger.debug(truncated_message)
        else:
            self._logger.debug(message)
    
    def _limit_output_lines(self, text, max_lines=200):
        """
        限制输出文本的行数，只保留最后 max_lines 行
        
        参数:
            text (str): 要处理的文本
            max_lines (int): 最大保留行数
            
        返回:
            str: 处理后的文本
        """
        if not text:
            return text
            
        lines = text.splitlines()
        if len(lines) <= max_lines:
            return text
        
        return '\n'.join(lines[-max_lines:])
        
    def set_prompt_patterns(self, patterns):
        """
        设置自定义的shell提示符匹配模式
        
        参数:
            patterns (list): 正则表达式模式列表
        """
        if not isinstance(patterns, list):
            raise TypeError("Prompt patterns must be a list of regex strings")
        self._prompt_patterns = patterns
        
    def get_prompt_patterns(self):
        """
        获取当前的shell提示符匹配模式
        
        返回:
            list: 当前的正则表达式模式列表
        """
        return self._prompt_patterns.copy()
    
    def _run(self,
             command: str,
             reset_ssh: bool = False,
             tail_lines: int = 100,
             )->str:
        """
        执行远程命令
        """
        
        if reset_ssh:
            self.disconnect()
            self.connect()
            
            self.start_interactive_shell()
            
            self.pre_execute()
            
        if self._client is None:
            self.connect()
            
            self.start_interactive_shell()
        
        # 检查是否包含sudo命令，增加特殊处理
        is_sudo_command = 'sudo ' in command
        # 检查是否是下载或安装命令
        is_download_command = any(keyword in command.lower() for keyword in 
                               ['apt', 'apt-get', 'yum', 'dnf', 'pip', 'conda', 'npm', 'wget', 'curl', 'install', 'update', 'upgrade', 'git', 'clone'])
        # 检查是否是apt-get update命令
        is_apt_update = 'apt-get update' in command or 'apt update' in command
        # 检查是否是docker logs -f命令
        is_docker_logs_follow = 'docker logs -f' in command or 'docker logs --follow' in command
        
        if is_sudo_command:
            self._logger.info("检测到sudo命令，使用特殊处理逻辑")
            timeout = 30  # 超时时间增加为900秒
        elif is_apt_update:
            self._logger.info("检测到apt-get update命令，使用特殊处理逻辑")
            timeout = 30  # apt-get update命令使用更长的超时时间
        elif is_download_command:
            self._logger.info("检测到可能的下载或安装命令，增加超时时间")
            timeout = 30  # 下载命令使用更长的超时时间
        else:
            timeout = 30  # 超时时间增加为60秒
            
        # 对于docker logs -f命令，使用特殊处理
        if is_docker_logs_follow:
            self._logger.info("检测到docker logs -f命令，等待1秒后立即返回结果")
            # 发送命令前先清空缓冲区
            if self._channel.recv_ready():
                buffer_content = self._channel.recv(65535).decode('utf-8', errors='replace')
                
            # 发送命令
            self._channel.send(command + '\n')
            
            # 等待1秒
            time.sleep(1)
            
            # 读取所有可用输出
            output = ""
            while self._channel.recv_ready():
                part = self._channel.recv(65535).decode('utf-8', errors='replace')
                output += part
            
            # 如果需要限制行数，只保留最后的tail_lines行
            if tail_lines > 0 and output:
                lines = output.splitlines()
                if len(lines) > tail_lines:
                    output = '\n'.join(lines[-tail_lines:])
                
            return output
            
        # 默认应用优化设置
        result = self.execute_interactive_command(
            command, 
            tail_lines=tail_lines, 
            timeout=timeout,
            # 默认启用输出优化，不需要参数
        )
        
        return result
        
    def connect(self):
        """
        建立SSH连接
        
        返回:
            bool: 连接成功返回True，否则返回False
        """
        try:
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            connect_kwargs = {
                'hostname': self._host,
                'port': self._port,
                'timeout': self._timeout
            }
            
            if self._username:
                connect_kwargs['username'] = self._username
            
            if self._password:
                connect_kwargs['password'] = self._password
            
            if self._key_filename and Path(self._key_filename).exists():
                connect_kwargs['key_filename'] = self._key_filename
            
            self._client.connect(**connect_kwargs)
            self._logger.info(f"成功连接到 {self._host}:{self._port}")
            return True
        except Exception as e:
            self._logger.error(f"连接到 {self._host}:{self._port} 失败: {str(e)}")
            return False
        
    def disconnect(self):
        """
        断开SSH连接
        """
        if self._client:
            self._client.close()
            self._logger.info(f"成功断开与 {self._host}:{self._port} 的连接")
            
    def start_interactive_shell(self):
        """
        启动交互式shell会话，保持状态
        
        返回:
            bool: 成功返回True，失败返回False
        """
        if not self._client:
            connected = self.connect()
            if not connected:
                return False
                
        try:
            self._channel = self._client.invoke_shell()
            self._interactive_mode = True
            # 等待shell初始化
            time.sleep(1)
            # 清除欢迎消息并记录提示符格式
            if self._channel.recv_ready():
                welcome = self._channel.recv(4096).decode('utf-8', errors='replace')
                # 记录原始欢迎消息，用于调试提示符格式
                self._logger.info(f"Shell欢迎消息: {repr(welcome)}")
                
                # 尝试检测提示符格式
                lines = welcome.splitlines()
                if lines and len(lines) > 0:
                    potential_prompt = lines[-1]
                    self._logger.info(f"潜在提示符格式: {repr(potential_prompt)}")
                    
                    # 测试当前模式是否匹配
                    for pattern in self._prompt_patterns:
                        if re.search(pattern, welcome, re.MULTILINE):
                            self._logger.info(f"提示符匹配模式: {pattern}")
                
            self._logger.info("交互式shell会话已启动")
            return True
        except Exception as e:
            self._logger.error(f"启动交互式shell失败: {str(e)}")
            self._interactive_mode = False
            return False
        
    def execute_interactive_command(self, command, blocking=True, timeout=30, buffer_size=65535, tail_lines=0, debug_mode=None):
        """
        在交互式会话中执行命令
        
        参数:
            command (str): 要执行的命令
            blocking (bool): 是否阻塞等待命令执行完成
            timeout (int): 最大等待时间(秒)
            buffer_size (int): 读取缓冲区大小
            tail_lines (int): 只返回输出的最后几行，0表示返回全部输出
            debug_mode (bool): 是否启用调试模式，True时保留提示符，None时使用实例默认设置
            
        返回:
            str: 命令输出结果
        """
        # 如果未指定debug_mode，使用实例的默认设置
        if debug_mode is None:
            debug_mode = self._debug_mode
        
        if not self._interactive_mode or not self._channel:
            if not self.start_interactive_shell():
                return "无法启动交互式shell"
        
        try:
            # 检查是否包含sudo命令
            is_sudo_command = 'sudo ' in command
            
            # 检查是否是apt相关命令
            is_apt_command = any(apt_cmd in command for apt_cmd in ['apt-get', 'apt'])
            
            # 检查是否是conda命令
            is_conda_command = 'conda ' in command
            
            # 检查是否是Docker命令
            is_docker_command = 'docker ' in command
            
            # 检查是否是Docker pull命令
            is_docker_pull = 'docker pull ' in command
            
            # 检查是否是Docker logs -f命令
            is_docker_logs_follow = 'docker logs -f' in command or 'docker logs --follow' in command
            
            # 检查是否是下载或安装命令
            is_download_command = any(keyword in command.lower() for keyword in 
                               ['apt', 'apt-get', 'yum', 'dnf', 'pip', 'conda', 'npm', 'wget', 'curl', 'install', 'update', 'upgrade', 'git', 'clone'])
            
            if is_sudo_command:
                self._logger.info("检测到sudo命令，使用特殊处理逻辑")
                timeout = 30  # 超时时间增加为900秒
            elif is_docker_pull:
                self._logger.info("检测到docker pull命令，使用特殊处理逻辑")
                timeout = 30  # Docker pull命令使用更长的超时时间 (1小时)
            elif is_docker_command:
                self._logger.info("检测到docker命令，使用特殊处理逻辑") 
                timeout = 30  # Docker命令使用更长的超时时间 (30分钟)
            elif is_apt_command:
                self._logger.info("检测到apt命令，使用特殊处理逻辑")
                timeout = 30  # apt命令使用更长的超时时间
            elif is_conda_command:
                self._logger.info("检测到conda命令，使用特殊处理逻辑")
                timeout = 30  # conda命令使用更长的超时时间
            elif is_download_command:
                self._logger.info("检测到可能的下载或安装命令，增加超时时间")
                timeout = 30  # 下载命令使用更长的超时时间
            else:
                timeout = 30  # 超时时间增加为60秒
            
            # 发送命令前先清空缓冲区
            if self._channel.recv_ready():
                buffer_content = self._channel.recv(buffer_size).decode('utf-8', errors='replace')
                self._logger.info(f"清除缓冲区，内容: {repr(buffer_content[-100:] if len(buffer_content) > 100 else buffer_content)}")
                
            # 发送命令
            self._logger.info(f"开始执行命令: {command}")
            self._channel.send(command + '\n')
            
            # 对于docker logs -f命令，只等待短暂时间获取最新日志
            if is_docker_logs_follow and not blocking:
                self._logger.info("docker logs -f命令，短暂等待获取最新日志")
                time.sleep(2)  # 等待2秒以获取初始日志输出
                output = ""
                while self._channel.recv_ready():
                    part = self._channel.recv(buffer_size).decode('utf-8', errors='replace')
                    output += part
                
                # 发送Ctrl+C中断日志跟踪
                self._channel.send('\x03')  # 发送Ctrl+C
                time.sleep(0.5)  # 等待命令终止
                
                # 如果需要截取最后几行
                if tail_lines > 0 and output:
                    output_lines = output.splitlines()
                    output = '\n'.join(output_lines[-tail_lines:])
                    
                return output
            
            # 增加延迟以避免立即触发命令完成检测，尤其是对于长时间运行的命令
            time.sleep(2)
            
            # 读取输出
            output = ""
            
            if blocking:
                # 阻塞模式 - 等待命令执行完成
                start_time = time.time()
                last_output_change_time = start_time
                last_output_length = 0
                current_time = start_time  # 初始化current_time变量
                
                # 用于检测shell提示符的正则表达式模式
                prompt_patterns = self.get_prompt_patterns()
                
                has_data = False
                command_completed = False
                sudo_password_detected = False
                sudo_password_sent = False  # 跟踪是否已发送密码
                pager_detected = False  # 跟踪是否检测到分页器
                interactive_prompt_detected = False  # 跟踪是否检测到交互式提示
                activity_detected = False  # 初始化活动检测变量
                
                # 特征检测 - 用于Docker容器中的特殊情况
                known_prompts = self._known_prompts
                
                # 用于检测重复的锁等待消息
                lock_wait_messages = []
                lock_wait_repeats = 0
                last_lock_message = ""
                
                # 用于检测下载/进度条模式
                download_mode_detected = False
                last_progress_time = start_time
                
                while True:
                    # 检查是否有可读数据
                    if self._channel.recv_ready():
                        has_data = True
                        part = self._channel.recv(buffer_size).decode('utf-8', errors='replace')
                        output += part
                        
                        # 记录日志，便于调试
                        # 限制debug日志输出，只显示最新的部分内容
                        if len(part) > 400:  # 如果新接收的内容较长
                            self._limited_debug_log(f"接收到新输出(已截断): {repr(part[-400:])}")
                        else:
                            self._limited_debug_log(f"接收到新输出: {repr(part)}")
                        
                        # 如果输出过长，只保留最新的200行
                        if len(output.splitlines()) > 200:
                            output = self._limit_output_lines(output)
                        
                        # 无论输出内容是否相同，只要收到新数据就更新时间戳
                        last_output_change_time = time.time()
                        last_output_length = len(output)
                        
                        # 标记活动状态，用于防止不必要的超时
                        activity_detected = False
                        
                        # 检查是否是conda环境创建命令
                        is_conda_create = 'conda create' in command
                        
                        # 检查是否是apt更新命令
                        is_apt_update = 'apt-get update' in command or 'apt update' in command
                        
                        # 检查是否是Docker pull命令
                        is_docker_pull = 'docker pull' in command
                        
                        # 检测是否是下载进度条模式
                        for progress_pattern in self._download_progress_patterns:
                            if re.search(progress_pattern, part, re.MULTILINE):
                                if not download_mode_detected:
                                    self._logger.info(f"检测到下载/进度条模式: {progress_pattern}")
                                    download_mode_detected = True
                                last_progress_time = time.time()
                                activity_detected = True
                                
                                # 特别是对于conda命令，确保我们继续等待，不提前完成
                                if is_conda_command and any(marker in part for marker in [
                                    "Downloading and Extracting Packages",
                                    "Preparing transaction",
                                    "Verifying transaction",
                                    "Executing transaction"
                                ]):
                                    self._logger.info(f"检测到conda安装过程中的关键状态: {part.strip()}")
                                    last_output_change_time = time.time()  # 更新时间戳
                                
                                # 检测Docker下载进度
                                if is_docker_command and any(marker in part for marker in [
                                    "Downloading",
                                    "Pulling",
                                    "Extracting",
                                    "Waiting",
                                    "Verifying"
                                ]):
                                    self._logger.info(f"检测到Docker操作进度更新: {part.strip()[-50:]}")
                                    last_output_change_time = time.time()  # 更新时间戳
                                break
                        
                        # 检查是否检测到分页器提示
                        pager_detected = False
                        interactive_prompt_detected = False
                        
                        # 检测锁等待消息
                        if "Waiting for cache lock" in part or "Could not get lock" in part:
                            current_message = part.strip()
                            
                            # 如果消息相似于上一条，增加计数
                            if last_lock_message and (
                                "Waiting for cache lock" in current_message and "Waiting for cache lock" in last_lock_message or
                                "Could not get lock" in current_message and "Could not get lock" in last_lock_message
                            ):
                                lock_wait_repeats += 1
                                self._logger.info(f"检测到重复的锁等待消息，当前重复次数: {lock_wait_repeats}")
                                
                                # 如果重复次数达到阈值，中断命令
                                if lock_wait_repeats >= 3:
                                    self._logger.info("检测到多次重复的锁等待消息，终止命令执行")
                                    interactive_prompt_detected = True
                                    command_completed = False
                                    output += "\n[系统检测到重复的锁等待消息，需要用户处理]"
                                    break
                            else:
                                # 新的锁消息
                                last_lock_message = current_message
                                lock_wait_repeats = 1
                        
                        # 首先检查是否有交互式提示，需要用户输入
                        for prompt_pattern in self._interactive_prompt_patterns:
                            if re.search(prompt_pattern, output, re.MULTILINE):
                                interactive_prompt_detected = True
                                self._logger.info(f"检测到交互式提示: {prompt_pattern}，等待用户输入")
                                # 不自动回应，让用户处理
                                break
                                
                        # 特殊检查：apt安装包提示
                        if not interactive_prompt_detected and "Do you want to continue? [Y/n]" in output:
                            interactive_prompt_detected = True
                            self._logger.info("检测到apt安装提示，等待用户输入")
                        
                        # 特殊检查：conda等工具的Proceed提示
                        if not interactive_prompt_detected and "Proceed ([y]/n)?" in output:
                            interactive_prompt_detected = True
                            self._logger.info("检测到Proceed确认提示，等待用户输入")
                            # 不自动回应，让用户处理
                            command_completed = False
                            break
                        
                        # 特殊检查：conda环境删除确认提示
                        if not interactive_prompt_detected and (
                            "Do you wish to continue?" in output or 
                            "(y/[n])?" in output or
                            ("will be deleted" in output and "continue" in output)):
                            interactive_prompt_detected = True
                            self._logger.info("检测到conda环境删除确认提示，等待用户输入")
                            command_completed = False
                            break
                        
                        # 特殊检查：Ubuntu添加组件提示
                        if not interactive_prompt_detected and (
                            "Press [ENTER] to continue" in output or
                            ("component" in output and "repositories" in output and "Press" in output) or
                            "Adding component" in output):
                            interactive_prompt_detected = True
                            self._logger.info("检测到Ubuntu添加组件提示，等待用户输入")
                            command_completed = False
                            break
                        
                        if interactive_prompt_detected:
                            # 所有交互式提示都直接中断执行，等待用户处理
                            command_completed = False
                            break
                        
                        # 先检查是否到达了内容末尾
                        if '(END)' in output or output.rstrip().endswith('(END)'):
                            # 检查一下是否有明显的用户交互提示
                            last_lines = output.splitlines()[-5:] if output.splitlines() else []
                            has_prompt = False
                            for line in last_lines:
                                # 检查是否包含常见的交互提示词
                                if any(keyword in line.lower() for keyword in [
                                    'continue', 'yes', 'no', 'y/n', 'select', 'choice',
                                    'enter', 'proceed', 'confirm', 'abort', 'accept',
                                    'press [enter]', 'press enter', 'ctrl-c', 'component', 'repository'
                                ]):
                                    has_prompt = True
                                    self._logger.info(f"检测到可能的用户交互提示: {line}")
                                    break
                            
                            if has_prompt:
                                self._logger.info("(END)后检测到可能的交互提示，等待用户输入")
                                command_completed = False
                                break
                            else:
                                pager_detected = True
                                self._logger.info("检测到分页内容已结束 (END)，发送 q 退出分页器")
                                time.sleep(0.5)
                                self._channel.send("q")  # 使用q键退出分页器
                                last_output_change_time = time.time()  # 更新时间戳
                        else:
                            # 检查常规分页器提示
                            for pager_pattern in self._pager_patterns:
                                if re.search(pager_pattern, output, re.MULTILINE):
                                    pager_detected = True
                                    self._logger.info(f"检测到分页器提示: {pager_pattern}")
                                    # 发送空格或回车以继续
                                    time.sleep(0.1)
                                    self._logger.info("发送分页器继续键...")
                                    self._channel.send(" ")  # 使用空格键继续
                                    last_output_change_time = time.time()  # 更新时间戳
                                    break
                        
                        if pager_detected:
                            # 如果检测到分页器，继续等待新输出
                            continue
                        
                        # 检查是否包含密码提示符
                        for exclude_pattern in self._exclude_patterns:
                            if re.search(exclude_pattern, output, re.MULTILINE):
                                sudo_password_detected = True
                                self._logger.info(f"检测到需要输入密码: {exclude_pattern}")
                                # 如果有密码，自动输入密码
                                if self._password and sudo_password_detected and not sudo_password_sent:
                                    time.sleep(0.5)  # 稍等片刻，确保密码提示完全显示
                                    self._logger.info("发送密码...")
                                    self._channel.send(self._password + '\n')
                                    sudo_password_sent = True  # 标记已发送密码
                                    sudo_password_detected = False  # 重置检测标志
                                    # 更新时间戳，以便有足够时间等待命令完成
                                    last_output_change_time = time.time()
                                    break
                        
                        # 只在未检测到密码提示时检查命令是否完成
                        if not sudo_password_detected:
                            # 对于apt-get update命令，检查特定完成标记
                            if is_apt_update and any(marker in output for marker in [
                                "Reading package lists... Done",
                                "Building dependency tree... Done", 
                                "Reading state information... Done"
                            ]):
                                # 确保这些标记是输出的最后部分
                                lines = output.splitlines()
                                last_20_lines = lines[-20:] if len(lines) > 20 else lines
                                last_20_text = '\n'.join(last_20_lines)
                                
                                # 检查是否下载已完成 - 所有Done标记都需要存在且在输出的最后部分
                                if all(marker in last_20_text for marker in [
                                    "Reading package lists... Done",
                                    "Building dependency tree... Done", 
                                    "Reading state information... Done"
                                ]) and not any(downloading_marker in last_20_text for downloading_marker in [
                                    "%]", "MB/s", "Get:", "Fetched", "Waiting for headers"
                                ]):
                                    # 检查是否有一段安静期，表示命令可能已完成
                                    current_time = time.time()
                                    if current_time - last_output_change_time > 5:  # 如果5秒内没有新输出
                                        self._logger.info("检测到apt-get update可能已完成，5秒内无新输出")
                                        # 在调试模式下，尝试获取更多数据以确保捕获到提示符
                                        if debug_mode and self._channel.recv_ready():
                                            additional_output = self._channel.recv(buffer_size).decode('utf-8', errors='replace')
                                            if additional_output:
                                                output += additional_output
                                                self._logger.info(f"调试模式下获取额外提示符数据: {repr(additional_output)}")
                                                last_output_change_time = time.time()
                                        command_completed = True
                                        break
                            
                            # 对于conda create命令，检查是否有特定的完成标记
                            if is_conda_create and "To activate this environment, use" in output:
                                command_completed = True
                                self._logger.info("检测到conda环境创建完成标记")
                                break
                                
                            # 检查是否出现了shell提示符，表示命令已完成
                            for i, pattern in enumerate(prompt_patterns):
                                if re.search(pattern, output, re.MULTILINE):
                                    # 检查是否是排除的模式
                                    is_excluded = False
                                    for exclude_pattern in self._exclude_patterns:
                                        if re.search(exclude_pattern, output, re.MULTILINE):
                                            is_excluded = True
                                            self._logger.info(f"提示符匹配被排除规则覆盖: {exclude_pattern}")
                                            break
                                    
                                    # 检查是否正在下载 - 避免在下载过程中提前退出
                                    if is_apt_command:
                                        lines = output.splitlines()
                                        last_10_lines = lines[-10:] if len(lines) > 10 else lines
                                        last_10_text = '\n'.join(last_10_lines)
                                        
                                        # 如果最近输出显示正在下载，则不认为命令已完成
                                        if any(downloading_marker in last_10_text for downloading_marker in [
                                            "%]", "MB/s", "Get:", "Fetched", "Waiting for headers"
                                        ]):
                                            self._logger.info("检测到可能的命令完成，但下载仍在进行，继续等待...")
                                            is_excluded = True
                                    
                                    if not is_excluded:
                                        command_completed = True
                                        self._logger.info(f"命令完成，匹配到提示符模式[{i}]: {pattern}")
                                        break
                                else:
                                    # 输出最后20个字符，便于调试
                                    last_chars = output[-min(20, len(output)):]
                                    self._limited_debug_log(f"模式[{i}]不匹配: {pattern}, 末尾字符: {repr(last_chars)}")
                            
                            # 特征检测 - 检查输出末尾是否包含已知的提示符特征
                            if not command_completed:
                                last_line = output.splitlines()[-1] if output.splitlines() else ""
                                if any(prompt in last_line for prompt in known_prompts):
                                    # 确保不是密码提示
                                    is_excluded = False
                                    for exclude_pattern in self._exclude_patterns:
                                        if re.search(exclude_pattern, last_line):
                                            is_excluded = True
                                            self._logger.info(f"特征检测匹配被排除规则覆盖: {exclude_pattern}")
                                            break
                                    
                                    # 如果是apt命令，检查是否正在下载，避免提前退出
                                    if is_apt_command and not is_excluded:
                                        lines = output.splitlines()
                                        last_10_lines = lines[-10:] if len(lines) > 10 else lines
                                        last_10_text = '\n'.join(last_10_lines)
                                        
                                        # 如果最近输出显示正在下载，则不认为命令已完成
                                        if any(downloading_marker in last_10_text for downloading_marker in [
                                            "%]", "MB/s", "Get:", "Fetched", "Waiting for headers"
                                        ]):
                                            self._logger.info("特征检测到可能的命令完成，但下载仍在进行，继续等待...")
                                            is_excluded = True
                                    
                                    if not is_excluded:
                                        command_completed = True
                                        self._logger.info(f"命令完成，通过特征检测匹配: {repr(last_line)}")
                            
                            if command_completed:
                                # 提取提示符之前的输出
                                prompt_text = ""
                                for pattern in prompt_patterns:
                                    match = re.search(pattern, output, re.MULTILINE)
                                    if match:
                                        # 截取到提示符之前的部分作为实际输出
                                        prompt_text = output[match.start():]
                                        
                                        # 在调试模式下保留提示符，否则移除
                                        if not debug_mode:
                                            output = output[:match.start()]
                                        
                                        self._logger.info(f"提取到提示符: '{prompt_text}'")
                                        break
                                break
                    else:
                        # 无数据可读时检查是否超时
                        current_time = time.time()
                        
                        # 对于下载模式，使用更宽松的超时策略
                        if download_mode_detected:
                            # 只有在下载模式下超过3分钟没有进度更新时才考虑超时
                            if current_time - last_progress_time > 180:
                                # 对于Docker pull命令，给予更长的耐心时间
                                if is_docker_pull and current_time - start_time < 3600:  # 1小时内都不过早判断超时
                                    self._logger.info(f"Docker pull操作中，给予更多耐心等待时间")
                                    time.sleep(2)  # 稍作等待
                                    continue
                                # 对于Docker命令，给予更长的耐心时间
                                elif is_docker_command and current_time - start_time < 1800:  # 30分钟内都不过早判断超时
                                    self._logger.info(f"Docker操作中，给予更多耐心等待时间")
                                    time.sleep(2)  # 稍作等待
                                    continue
                                # 对于conda create命令，给予更长的耐心时间
                                elif is_conda_create and current_time - start_time < 1800:  # 30分钟内都不过早判断超时
                                    self._logger.info(f"conda创建环境中，给予更多耐心等待时间")
                                    time.sleep(2)  # 稍作等待
                                    continue
                                
                                self._logger.warning(f"下载模式下长时间无进度更新 ({(current_time - last_progress_time):.1f}秒)")
                                # 尝试按回车键或空格键继续
                                self._channel.send('\n')
                                self._channel.send(' ')
                                time.sleep(1)  # 等待一下看是否有响应
                                # 重置时间戳，给予更多时间
                                last_progress_time = current_time
                                last_output_change_time = current_time
                        
                        # 检查是否有命令已完成的迹象
                        # 检查最后一行是否包含提示符
                        last_line = output.splitlines()[-1] if output.splitlines() else ""
                        prompt_detected = any(prompt in last_line for prompt in known_prompts)
                        
                        # 如果检测到命令可能已完成，再尝试读取一次
                        if prompt_detected:
                            time.sleep(0.5)
                            if self._channel.recv_ready():
                                part = self._channel.recv(buffer_size).decode('utf-8', errors='replace')
                                output += part
                                last_output_change_time = time.time()
                                continue
                            else:
                                # 很可能命令已经完成，设置完成标志并退出循环
                                command_completed = True
                                self._logger.info(f"检测到命令可能已完成: {repr(last_line)}")
                                break
                        
                        # 检查总时间是否超过timeout，强制退出
                        if current_time - start_time > timeout:
                            # 下载模式下，只要进度在最近3分钟内有更新，就继续等待
                            if download_mode_detected and current_time - last_progress_time < 180:
                                # 继续等待，不超时
                                self._logger.info(f"下载模式中，虽然总时间已超过timeout，但进度仍在更新，继续等待")
                                time.sleep(2)
                                continue
                            
                            # Docker命令特殊处理 - 只要有活动就不超时
                            if is_docker_command and (activity_detected or current_time - last_output_change_time < 30):
                                self._logger.info(f"Docker命令仍在执行，检测到活动或最近30秒内有输出，继续等待")
                                time.sleep(2)
                                # 重置活动检测标志
                                activity_detected = False
                                continue
                            
                            # 如果已经有命令输出且最后一行包含提示符，可能命令已完成
                            if output and any(prompt in last_line for prompt in known_prompts):
                                self._logger.info(f"检测到超时但命令可能已完成: {repr(last_line)}")
                                command_completed = True
                                break
                        
                            self._logger.warning(f"命令执行超时 (总时间: {current_time - start_time:.1f}秒, 最后更新: {current_time - last_output_change_time:.1f}秒前)")
                            output += "\n[命令执行超时]"
                            break

                # 如果长时间没有输出更新，但还未达到总超时时间，发送一个回车尝试触发响应
                current_time = time.time()  # 确保current_time总是被更新
                if current_time - last_output_change_time > 15 and current_time - start_time < timeout - 20 and not download_mode_detected:
                    self._logger.info("长时间无输出更新，发送回车尝试触发响应")
                    self._channel.send('\n')
                    last_output_change_time = current_time  # 重置时间戳
            else:
                # 非阻塞模式 - 等待固定时间
                time.sleep(2)
                while self._channel.recv_ready():
                    part = self._channel.recv(buffer_size).decode('utf-8', errors='replace')
                    output += part
                    if len(part) < buffer_size:
                        break
            
            # 如果需要截取最后几行
            if tail_lines > 0 and output:
                output_lines = output.splitlines()
                output = '\n'.join(output_lines[-tail_lines:])
                
            # 确保输出不仅仅是发送的命令本身
            if output.strip() == command.strip():
                self._logger.warning("检测到输出与命令相同，可能是提前终止。添加额外等待...")
                # 再等待几秒以获取可能的输出
                time.sleep(5)
                if self._channel.recv_ready():
                    additional_output = self._channel.recv(buffer_size).decode('utf-8', errors='replace')
                    output += additional_output
                    self._logger.info(f"获取到额外输出: {repr(additional_output)}")
                
            # 限制日志输出量，只显示最后400个字符或少于200行的完整输出
            output_for_log = output[-400:] if len(output) > 400 else output
            # 确保日志输出不超过最大行数限制
            self._logger.info(f"get current output: {output_for_log}")
            return output
        except Exception as e:
            self._logger.error(f"执行交互式命令失败: {str(e)}")
            return f"执行命令失败: {str(e)}"
        
    def execute_streaming_command(self, command, timeout=360, buffer_size=1024, tail_lines=0, debug_mode=None):
        """
        流式执行命令，实时返回结果
        
        参数:
            command (str): 要执行的命令
            timeout (int): 最大等待时间(秒)
            buffer_size (int): 读取缓冲区大小
            tail_lines (int): 只返回输出的最后几行，0表示返回全部输出
            debug_mode (bool): 是否启用调试模式，True时保留提示符，None时使用实例默认设置
            
        返回:
            str: 命令完整输出结果
        """
        # 如果未指定debug_mode，使用实例的默认设置
        if debug_mode is None:
            debug_mode = self._debug_mode
        
        if not self._interactive_mode or not self._channel:
            if not self.start_interactive_shell():
                return "无法启动交互式shell"
        
        try:
            # 检查是否包含sudo命令
            is_sudo_command = 'sudo ' in command
            # 检查是否是下载或安装命令
            is_download_command = any(keyword in command.lower() for keyword in 
                                   ['apt', 'apt-get', 'yum', 'dnf', 'pip', 'conda', 'npm', 'wget', 'curl', 'install', 'update', 'upgrade', 'git', 'clone'])
            
            # 检查是否是apt相关命令
            is_apt_command = any(apt_cmd in command for apt_cmd in ['apt-get', 'apt'])
            
            if is_sudo_command:
                self._logger.info("流式命令中检测到sudo命令，使用特殊处理逻辑")
                timeout = 30  # 超时时间
            elif is_apt_command:
                self._logger.info("流式命令中检测到apt命令，使用特殊处理逻辑")
                timeout = 30  # apt命令使用更长的超时时间
            elif is_download_command:
                self._logger.info("流式命令中检测到可能的下载或安装命令，增加超时时间")
                timeout = 30  # 下载命令使用更长的超时时间
            
            # 发送命令前先清空缓冲区
            if self._channel.recv_ready():
                buffer_content = self._channel.recv(buffer_size).decode('utf-8', errors='replace')
                self._logger.info(f"流式命令清除缓冲区，内容: {repr(buffer_content[-100:] if len(buffer_content) > 100 else buffer_content)}")
                
            # 发送命令
            self._logger.info(f"开始流式执行命令: {command}")
            self._channel.send(command + '\n')
            
            # 增加延迟以避免立即触发命令完成检测，尤其是对于长时间运行的命令
            time.sleep(2)
            
            # 流式读取输出
            output = ""
            start_time = time.time()
            last_output_change_time = start_time
            last_output_length = 0
            current_time = start_time  # 初始化current_time变量
            
            # 用于检测shell提示符的正则表达式模式
            prompt_patterns = self.get_prompt_patterns()
            
            command_completed = False
            sudo_password_detected = False
            sudo_password_sent = False  # 跟踪是否已发送密码
            
            # 特征检测 - 用于Docker容器中的特殊情况
            known_prompts = [
                "(base) developer@", 
                "~/code$", 
                "@110dce07d505:",
                "root@",
                "AquaTao@",
                "aquatao@",  # 添加小写版本
                # 添加常见的apt-get完成后可能出现的提示符
                "]:~#",      # root用户家目录提示符
                "]:/#",      # root用户根目录提示符
                # 通用的基于用户名的提示符
                "@ubuntu:",
                "@debian:"
            ]
            
            # 用于检测重复的锁等待消息
            lock_wait_messages = []
            lock_wait_repeats = 0
            last_lock_message = ""
            
            # 用于检测下载/进度条模式
            download_mode_detected = False
            last_progress_time = start_time
            
            while True:
                if self._channel.recv_ready():
                    part = self._channel.recv(buffer_size).decode('utf-8', errors='replace')
                    output += part
                    print(part, end="", flush=True)  # 实时输出到控制台
                    
                    # 记录日志，便于调试
                    # 限制debug日志输出，只显示最新的部分内容
                    if len(part) > 400:  # 如果新接收的内容较长
                        self._limited_debug_log(f"流式命令接收到新输出(已截断): {repr(part[-400:])}")
                    else:
                        self._limited_debug_log(f"流式命令接收到新输出: {repr(part)}")
                    
                    # 如果输出过长，只保留最新的200行
                    if len(output.splitlines()) > 200:
                        output = self._limit_output_lines(output)
                    
                    # 无论输出内容是否相同，只要收到新数据就更新时间戳
                    last_output_change_time = time.time()
                    last_output_length = len(output)
                    
                    # 标记活动状态，用于防止不必要的超时
                    activity_detected = False
                    
                    # 检查是否是conda环境创建命令
                    is_conda_create = 'conda create' in command
                    
                    # 检查是否是apt更新命令
                    is_apt_update = 'apt-get update' in command or 'apt update' in command
                    
                    # 检查是否是Docker pull命令
                    is_docker_pull = 'docker pull' in command
                    
                    # 检测是否是下载进度条模式
                    for progress_pattern in self._download_progress_patterns:
                        if re.search(progress_pattern, part, re.MULTILINE):
                            if not download_mode_detected:
                                self._logger.info(f"流式命令检测到下载/进度条模式: {progress_pattern}")
                                download_mode_detected = True
                            last_progress_time = time.time()
                            activity_detected = True
                            break
                    
                    # 检测锁等待消息
                    if "Waiting for cache lock" in part or "Could not get lock" in part:
                        current_message = part.strip()
                        
                        # 如果消息相似于上一条，增加计数
                        if last_lock_message and (
                            "Waiting for cache lock" in current_message and "Waiting for cache lock" in last_lock_message or
                            "Could not get lock" in current_message and "Could not get lock" in last_lock_message
                        ):
                            lock_wait_repeats += 1
                            self._logger.info(f"流式命令检测到重复的锁等待消息，当前重复次数: {lock_wait_repeats}")
                            
                            # 如果重复次数达到阈值，中断命令
                            if lock_wait_repeats >= 3:
                                self._logger.info("流式命令检测到多次重复的锁等待消息，终止命令执行")
                                print("\n[系统检测到重复的锁等待消息，需要用户处理]", flush=True)
                                output += "\n[系统检测到重复的锁等待消息，需要用户处理]"
                                command_completed = True  # 设置为True以结束循环
                                break
                        else:
                            # 新的锁消息
                            last_lock_message = current_message
                            lock_wait_repeats = 1
                    
                    # 检查是否包含密码提示符
                    for exclude_pattern in self._exclude_patterns:
                        if re.search(exclude_pattern, output, re.MULTILINE):
                            sudo_password_detected = True
                            self._logger.info(f"流式命令检测到需要输入密码: {exclude_pattern}")
                            # 如果有密码，自动输入密码
                            if self._password and sudo_password_detected and not sudo_password_sent:
                                time.sleep(0.5)  # 稍等片刻，确保密码提示完全显示
                                self._logger.info("流式命令发送密码...")
                                self._channel.send(self._password + '\n')
                                sudo_password_sent = True  # 标记已发送密码
                                sudo_password_detected = False  # 重置标志
                                # 更新时间戳，以便有足够时间等待命令完成
                                last_output_change_time = time.time()
                                break
                    
                    # 只在未检测到密码提示时检查命令是否完成
                    if not sudo_password_detected:
                        # 对于apt-get update命令，检查特定完成标记
                        if is_apt_update and any(marker in output for marker in [
                            "Reading package lists... Done",
                            "Building dependency tree... Done", 
                            "Reading state information... Done"
                        ]):
                            # 确保这些标记是输出的最后部分
                            lines = output.splitlines()
                            last_20_lines = lines[-20:] if len(lines) > 20 else lines
                            last_20_text = '\n'.join(last_20_lines)
                            
                            # 检查是否下载已完成 - 所有Done标记都需要存在且在输出的最后部分
                            if all(marker in last_20_text for marker in [
                                "Reading package lists... Done",
                                "Building dependency tree... Done", 
                                "Reading state information... Done"
                            ]) and not any(downloading_marker in last_20_text for downloading_marker in [
                                "%]", "MB/s", "Get:", "Fetched", "Waiting for headers"
                            ]):
                                # 检查是否有一段安静期，表示命令可能已完成
                                current_time = time.time()
                                if current_time - last_output_change_time > 5:  # 如果5秒内没有新输出
                                    self._logger.info("流式命令检测到apt-get update可能已完成，5秒内无新输出")
                                    # 在调试模式下，尝试获取更多数据以确保捕获到提示符
                                    if debug_mode and self._channel.recv_ready():
                                        additional_output = self._channel.recv(buffer_size).decode('utf-8', errors='replace')
                                        if additional_output:
                                            output += additional_output
                                            self._logger.info(f"调试模式下获取额外提示符数据: {repr(additional_output)}")
                                            last_output_change_time = time.time()
                                    command_completed = True
                                    break
                        
                        # 检查是否出现了shell提示符，表示命令已完成
                        for i, pattern in enumerate(prompt_patterns):
                            if re.search(pattern, output, re.MULTILINE):
                                # 检查是否是排除的模式
                                is_excluded = False
                                for exclude_pattern in self._exclude_patterns:
                                    if re.search(exclude_pattern, output, re.MULTILINE):
                                        is_excluded = True
                                        self._logger.info(f"流式命令提示符匹配被排除规则覆盖: {exclude_pattern}")
                                        break
                                
                                # 检查是否正在下载 - 避免在下载过程中提前退出
                                if is_apt_command:
                                    lines = output.splitlines()
                                    last_10_lines = lines[-10:] if len(lines) > 10 else lines
                                    last_10_text = '\n'.join(last_10_lines)
                                    
                                    # 如果最近输出显示正在下载，则不认为命令已完成
                                    if any(downloading_marker in last_10_text for downloading_marker in [
                                        "%]", "MB/s", "Get:", "Fetched", "Waiting for headers"
                                    ]):
                                        self._logger.info("流式命令检测到可能的命令完成，但下载仍在进行，继续等待...")
                                        is_excluded = True
                                    
                                    if not is_excluded:
                                        command_completed = True
                                        self._logger.info(f"流式命令完成，匹配到提示符模式[{i}]: {pattern}")
                                        break
                            else:
                                # 输出最后20个字符，便于调试
                                last_chars = output[-min(20, len(output)):]
                                self._limited_debug_log(f"流式命令模式[{i}]不匹配: {pattern}, 末尾字符: {repr(last_chars)}")
                        
                        # 特征检测 - 检查输出末尾是否包含已知的提示符特征
                        if not command_completed:
                            last_line = output.splitlines()[-1] if output.splitlines() else ""
                            if any(prompt in last_line for prompt in known_prompts):
                                # 确保不是密码提示
                                is_excluded = False
                                for exclude_pattern in self._exclude_patterns:
                                    if re.search(exclude_pattern, last_line):
                                        is_excluded = True
                                        self._logger.info(f"流式命令特征检测匹配被排除规则覆盖: {exclude_pattern}")
                                        break
                                
                                # 如果是apt命令，检查是否正在下载，避免提前退出
                                if is_apt_command and not is_excluded:
                                    lines = output.splitlines()
                                    last_10_lines = lines[-10:] if len(lines) > 10 else lines
                                    last_10_text = '\n'.join(last_10_lines)
                                    
                                    # 如果最近输出显示正在下载，则不认为命令已完成
                                    if any(downloading_marker in last_10_text for downloading_marker in [
                                        "%]", "MB/s", "Get:", "Fetched", "Waiting for headers"
                                    ]):
                                        self._logger.info("特征检测到可能的命令完成，但下载仍在进行，继续等待...")
                                        is_excluded = True
                                    
                                    if not is_excluded:
                                        command_completed = True
                                        self._logger.info(f"流式命令完成，通过特征检测匹配: {repr(last_line)}")
                        
                        if command_completed:
                            # 提取提示符之前的输出
                            prompt_text = ""
                            for pattern in prompt_patterns:
                                match = re.search(pattern, output, re.MULTILINE)
                                if match:
                                    # 截取到提示符之前的部分作为实际输出
                                    prompt_text = output[match.start():]
                                    
                                    # 在调试模式下保留提示符，否则移除
                                    if not debug_mode:
                                        output = output[:match.start()]
                                    
                                    self._logger.info(f"流式命令提取到提示符: '{prompt_text}'")
                                    break
                            break
                else:
                    current_time = time.time()
                    
                    # 对于下载模式，使用更宽松的超时策略
                    if download_mode_detected:
                        # 只有在下载模式下超过3分钟没有进度更新时才考虑超时
                        if current_time - last_progress_time > 180:
                            # 对于Docker pull命令，给予更长的耐心时间
                            if is_docker_pull and current_time - start_time < 3600:  # 1小时内都不过早判断超时
                                self._logger.info(f"Docker pull操作中，给予更多耐心等待时间")
                                time.sleep(2)  # 稍作等待
                                continue
                            # 对于Docker命令，给予更长的耐心时间
                            elif is_docker_command and current_time - start_time < 1800:  # 30分钟内都不过早判断超时
                                self._logger.info(f"Docker操作中，给予更多耐心等待时间")
                                time.sleep(2)  # 稍作等待
                                continue
                            # 对于conda create命令，给予更长的耐心时间
                            elif is_conda_create and current_time - start_time < 1800:  # 30分钟内都不过早判断超时
                                self._logger.info(f"conda创建环境中，给予更多耐心等待时间")
                                time.sleep(2)  # 稍作等待
                                continue
                                
                            self._logger.warning(f"下载模式下长时间无进度更新 ({(current_time - last_progress_time):.1f}秒)")
                            # 尝试按回车键或空格键继续
                            self._channel.send('\n')
                            self._channel.send(' ')
                            time.sleep(1)  # 等待一下看是否有响应
                            # 重置时间戳，给予更多时间
                            last_progress_time = current_time
                            last_output_change_time = current_time
                    
                    # 检查是否有命令已完成的迹象
                    # 检查最后一行是否包含提示符
                    last_line = output.splitlines()[-1] if output.splitlines() else ""
                    prompt_detected = any(prompt in last_line for prompt in known_prompts)
                    
                    # 如果检测到命令可能已完成，再尝试读取一次
                    if prompt_detected:
                        time.sleep(0.5)
                        if self._channel.recv_ready():
                            part = self._channel.recv(buffer_size).decode('utf-8', errors='replace')
                            output += part
                            print(part, end="", flush=True)
                            last_output_change_time = time.time()
                            continue
                        else:
                            # 很可能命令已经完成，设置完成标志并退出循环
                            command_completed = True
                            self._logger.info(f"流式命令检测到命令可能已完成: {repr(last_line)}")
                            break
                    
                    # 检查总时间是否超过timeout，强制退出
                    if current_time - start_time > timeout:
                        # 下载模式下，只要进度在最近3分钟内有更新，就继续等待
                        if download_mode_detected and current_time - last_progress_time < 180:
                            # 继续等待，不超时
                            self._logger.info(f"流式命令下载模式中，虽然总时间已超过timeout，但进度仍在更新，继续等待")
                            time.sleep(2)
                            continue
                        
                        # Docker命令特殊处理 - 只要有活动就不超时
                        if is_docker_command and (activity_detected or current_time - last_output_change_time < 30):
                            self._logger.info(f"Docker命令仍在执行，检测到活动或最近30秒内有输出，继续等待")
                            time.sleep(2)
                            # 重置活动检测标志
                            activity_detected = False
                            continue
                        
                        # 如果已经有命令输出且最后一行包含提示符，可能命令已完成
                        if output and any(prompt in last_line for prompt in known_prompts):
                            self._logger.info(f"流式命令检测到超时但命令可能已完成: {repr(last_line)}")
                            command_completed = True
                            break
                    
                        self._logger.warning(f"流式命令执行超时 (总时间: {current_time - start_time:.1f}秒, 最后更新: {current_time - last_output_change_time:.1f}秒前)")
                        output += "\n[命令执行超时]"
                        print("\n[命令执行超时]", flush=True)
                        break
                
                # 如果长时间没有输出更新，但还未达到总超时时间，发送一个回车尝试触发响应
                current_time = time.time()  # 确保current_time总是被更新
                if current_time - last_output_change_time > 15 and current_time - start_time < timeout - 20 and not download_mode_detected:
                    self._logger.info("流式命令长时间无输出更新，发送回车尝试触发响应")
                    self._channel.send('\n')
                    last_output_change_time = current_time  # 重置时间戳
                    
                # 短暂等待以减少CPU使用
                time.sleep(0.1)
            
            # 如果需要截取最后几行
            if tail_lines > 0 and output:
                output_lines = output.splitlines()
                output = '\n'.join(output_lines[-tail_lines:])
                
            # 确保输出不仅仅是发送的命令本身
            if output.strip() == command.strip():
                self._logger.warning("流式命令检测到输出与命令相同，可能是提前终止。添加额外等待...")
                # 再等待几秒以获取可能的输出
                time.sleep(5)
                if self._channel.recv_ready():
                    additional_output = self._channel.recv(buffer_size).decode('utf-8', errors='replace')
                    output += additional_output
                    print(additional_output, end="", flush=True)  # 实时输出到控制台
                    self._logger.info(f"流式命令获取到额外输出: {repr(additional_output)}")
            
            return output
        except Exception as e:
            error_msg = f"流式执行命令失败: {str(e)}"
            self._logger.error(error_msg)
            return error_msg
        
    def add_pre_execute_command(self, command):
        """
        添加预执行命令
        """
        self._pre_execute_command.append(command)
        
    def pre_execute(self):
        """
        预执行命令
        """
        if not self._client:
            connected = self.connect()
            if not connected:
                return "无法连接到远程服务器"
            
            self.start_interactive_shell()
            
        print("Start pre_execute")
        for command in self._pre_execute_command:
            result = self.execute_interactive_command(command)
            print(f"pre_execute_command: {command} result: {result}")
    def init_ssh(self):
        """
        初始化SSH连接
        """
        self.connect()
        self.start_interactive_shell()
        
    def reset_ssh(self):
        """
        重置SSH连接
        """
        self.disconnect()
        self.connect()
        self.start_interactive_shell()
        
        
        
        
        
        
    
if __name__ == "__main__":
    # # 配置日志
    logging.basicConfig(level=logging.DEBUG, 
                      format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # ssh_tool = SSHTool(host="192.168.5.54", username="AquaTao", password="nl@YTno.1", debug_mode=True)
    ssh_tool = SSHTool(host="192.168.5.85", username="aqualab", password="dyy520")

    ssh_tool.init_ssh()
    # ssh_tool.add_pre_execute_command('docker exec -it a96ab3432739 /bin/bash')
    # ssh_tool.pre_execute()
    
    result = ssh_tool._run(' docker logs -f ragflow-server')
    print(result)
    
    # ssh_tool.execute_interactive_command('conda create -n test python=3.10')
    