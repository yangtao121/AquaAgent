from .agent_base import AgentBase
from AquaAgent import aqua_config

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from typing import Annotated, List
from typing_extensions import TypedDict
import operator

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage



sys_prompt = """
You are an Ubuntu system operation and maintenance expert. You can operate the user's computer using bash commands. The user will ask you various Ubuntu-related questions, and you need to solve the problems they raise. Follow the process strictly as outlined below:

step 1. First, obtain the version number of the user's system.
step 2. Based on the user's version number and any other relevant information, if the user provides an installation tutorial link, prioritize reading it by Scrape_web_content. If problems occur, search for relevant solutions on the internet, read by Scrape_web_content and summarize tutorials, with an emphasis on official sources.
step 3. Before installing any software, confirm whether the user has already installed it and if the software version matches the tutorial. If feedback indicates the software is installed but the version doesn't match, return to step 2 and continue.
step 4. Execute the commands from the tutorial and analyze the results. If problems arise, return to step 2.
step 5. Verify whether the installation was successful. If not, return to step 2 and retry.

Ubuntu User Guide:
1. Use curl instead of wget. If the user's computer doesn't have it installed, please install it.
2. If using Docker for deployment, first pull the relevant image with `docker pull` and then proceed with the deployment.

SSH Tool User Guide:
1. This tool is an interactive terminal, and the commands from the previous execution are cached. For example, if a confirmation action appears after executing a command, you need to identify it and provide the correct input. If necessary, reset the terminal.
2. If the operation carries low risk, you can confirm actions on behalf of the user, such as installing or removing a conda environment, and perform the operation directly.
3. The terminal only supports one command at each time. Do not use the `&&` symbol to execute multiple commands!
4. When performing sudo operations, the SSH tool automatically fills in the password, eliminating the need to manually enter it.
"""

class State(TypedDict):
    messages: Annotated[list, add_messages]
    conversation_count: Annotated[int, operator.add] = 0
    
    

class SystemOperationAgent(AgentBase):
    def __init__(self,
                 ):
        super().__init__()
        
        self.ubuntu_llm = aqua_config.llm_model_dict['common']
        
        llm_tools = [
            aqua_config.ssh_tool,
            aqua_config.web_scrape_tool,
            aqua_config.web_search_tool
        ]
        
        self.ubuntu_llm_with_tools = self.ubuntu_llm.bind_tools(llm_tools)
        
        
        self.sys_prompt = sys_prompt
        
        tools_node = ToolNode(llm_tools)
        
        # 组装agent
        self.agent_builder = StateGraph(State)
        
        self.agent_builder.add_node("get_system_prompt", self.get_system_prompt)
        self.agent_builder.add_node("chat_llm", self.chat_llm)
        self.agent_builder.add_node("tools", tools_node)
        
        self.agent_builder.add_edge(START, "get_system_prompt")
        self.agent_builder.add_edge("get_system_prompt", "chat_llm")
        self.agent_builder.add_conditional_edges(
                "chat_llm",
                tools_condition,
        )
        self.agent_builder.add_edge("tools", "chat_llm")
        
        memory_saver = MemorySaver()
        self.agent = self.agent_builder.compile(checkpointer=memory_saver)
    
    def get_system_prompt(self,state: State):
        if state["conversation_count"] == 0:
            return {"messages": [SystemMessage(content=self.sys_prompt)], "conversation_count": 1}
        return {"conversation_count": 1}
    
    def chat_llm(self,state: State):
        
            
        messages = state["messages"]
        
        
        return {"messages": [self.ubuntu_llm_with_tools.invoke(messages)]}
        
        
        
        
        