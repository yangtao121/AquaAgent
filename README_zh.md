# AquaAgent

[English](README.md) | [中文](README_zh.md)

## 安装和运行指南

### 1. 创建Conda环境
创建一个名为`aquaagent`的Python 3.12 Conda环境：
```bash
conda create --name aquaagent python=3.12 -y
```

### 2. 激活环境
激活`aquaagent`环境：
```bash
conda activate aquaagent
```

### 3. 安装依赖
为`sys_operator.py`安装所有必需的依赖：
```bash
conda install -n aquaagent pyyaml -y
pip install langchain-core langchain-openai langchain langchain-community
```
### 4. 编辑配置

根据您的需求编辑`config`文件夹中的YAML文件。

### 5. 运行脚本
在激活的环境中运行`sys_operator.py`：
```bash
python sys_operator.py
```

---

### 依赖概述
主要依赖及其用途：
- `pyyaml`：解析YAML配置文件。
- `langchain-core`：LangChain的核心功能。
- `langchain-openai`：与OpenAI的集成。
- `langchain`：语言模型链式操作。
- `langchain-community`：社区贡献的工具和模块。

---

### 故障排除
1. **缺少依赖**：  
   如果缺少模块，使用`pip install <模块名称>`安装。

2. **环境冲突**：  
   如果依赖版本冲突，请重新创建Conda环境。

3. **配置文件**：  
   确保`config/cloud.yaml`存在且路径正确。

---

### 示例输出
成功执行将记录系统操作结果。 