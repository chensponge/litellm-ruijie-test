FROM python:3.11-slim

WORKDIR /app

# 用清华 PyPI 源安装依赖，速度快还稳定
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制源码并安装 LiteLLM
COPY . .
RUN pip install --no-cache-dir -e . -i https://pypi.tuna.tsinghua.edu.cn/simple

EXPOSE 4000

CMD ["litellm", "--config", "/app/config.yaml", "--port", "4000"]
