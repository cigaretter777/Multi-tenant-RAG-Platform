FROM artifacth.sail-cloud.com/zzfgs/wencheng/embedding:v0.0.1-14

# 设置工作目录
# WORKDIR /app

# 更新包列表并安装必要的依赖
# 更新包列表并安装必要的依赖
# RUN apt-get update && \
#    apt-get install -y \
#    curl \
#    && rm -rf /var/lib/apt/lists/*

# 设置时区为上海（中国）
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 设置工作目录
WORKDIR /workspace
COPY . /workspace

# RUN export NLTK_DATA=/workspace/tmp/nltk_data

# RUN pip3 uninstall llama-index
# RUN apt-get update && apt-get install -y python3 python3-pip
RUN pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple
RUN pip3 install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple

EXPOSE 8000

CMD ["python3","-u", "api.py"]
