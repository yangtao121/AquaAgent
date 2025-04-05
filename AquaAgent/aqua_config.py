from yaml import load, dump
from yaml import Loader, Dumper
from pprint import pprint

class AquaConfig:
    """
    用于读取配置，获取LLM模型，工具，数据库等配置信息
    """
    def __init__(self):
        
        self.llm_model_dict = {}
        self.llm_model_config = None
        self.tool_config = None
        
        # SSH_Tool
        self.ssh_tool = None
        
        # Web_Scrape_Tool
        self.web_scrape_tool = None
        
        # Web_Search_Tool
        self.web_search_tool = None
        

    def load_config(self, config_path: str):
        with open(config_path, 'r') as f:
            config = load(f, Loader=Loader)
            
        self.llm_model_config = config['LLMs']
        self.tool_config = config['Tools']
        
        self.init_llm_model()
        self.init_tool()
        
    
    def init_llm_model(self):
        for llm_model_name, llm_model_config in self.llm_model_config.items():
            
            llm_type = llm_model_config['type']
            
            if llm_type == 'ollama':
                from langchain_ollama import ChatOllama
                
                llm = ChatOllama(
                    **llm_model_config['params']
                )
                
                self.llm_model_dict[llm_model_name] = llm
                
            elif llm_type == 'openai':
                from langchain_openai import ChatOpenAI
                
                llm = ChatOpenAI(
                    **llm_model_config['params']
                )
                
                self.llm_model_dict[llm_model_name] = llm
                
            else:
                raise ValueError(f'Unsupported LLM type: {llm_type}')
            
    def init_tool(self):
        from AquaAgent.core.tool import ObtainWebContentTool, SearxSearchTool, SSHTool, TavilySearchTool
                
        # SSH_Tool
        
        print("#############init ssh tool: #############")
        debug_mode = self.tool_config['SSH_Tool']['params']['debug_mode'] 
        
        if debug_mode:
            import logging
            logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.ssh_tool = SSHTool(
            **self.tool_config['SSH_Tool']['params']
        )
        self.ssh_tool.init_ssh()
        
        if "pre_execute" in self.tool_config['SSH_Tool']:
            for command in self.tool_config['SSH_Tool']['pre_execute']:
                self.ssh_tool.add_pre_execute_command(command)
            
        self.ssh_tool.pre_execute()
        print("#############ssh tool init success#############")
        
        # Web_Scrape_Tool
        self.web_scrape_tool = ObtainWebContentTool()
        
        # Web_Search_Tool
        web_search_module_name = self.tool_config['Web_Search_Tool']['name']
        
        eval_web_search_tool = eval(web_search_module_name)
        
        self.web_search_tool = eval_web_search_tool(
            **self.tool_config['Web_Search_Tool']['params']
        ).get_searh_tool()
            