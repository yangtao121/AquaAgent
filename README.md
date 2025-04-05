# AquaAgent

[English](README.md) | [中文](README_zh.md)

## Installation and Running Guide

### 1. Create Conda Environment
Create a Conda environment named `aquaagent` with Python 3.12:
```bash
conda create --name aquaagent python=3.12 -y
```

### 2. Activate Environment
Activate the `aquaagent` environment:
```bash
conda activate aquaagent
```

### 3. Install Dependencies
Install all required dependencies for `sys_operator.py`:
```bash
conda install -n aquaagent pyyaml -y
pip install langchain-core langchain-openai langchain langchain-community
```
### 4. Edit config

Edit the YAML file in the ``config`` folder according to your needs.

### 5. Run the Script
Run `sys_operator.py` in the activated environment:
```bash
python sys_operator.py
```

---

### Dependency Overview
Key dependencies and their purposes:
- `pyyaml`: Parses YAML configuration files.
- `langchain-core`: Core functionality for LangChain.
- `langchain-openai`: Integration with OpenAI.
- `langchain`: Language model chaining operations.
- `langchain-community`: Community-contributed tools and modules.

---

### Troubleshooting
1. **Missing Dependencies**:  
   If a module is missing, install it with `pip install <module_name>`.

2. **Environment Conflicts**:  
   Recreate the Conda environment if dependency versions conflict.

3. **Configuration File**:  
   Ensure `config/cloud.yaml` exists and the path is correct.

---

### Example Output
Successful execution will log system operation results.
