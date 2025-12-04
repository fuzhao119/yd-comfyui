#!/bin/bash

echo "查找占用 8188 端口的进程..."
PID=$(lsof -ti:8188)

if [ -n "$PID" ]; then
    echo "发现进程 PID: $PID，正在终止..."
    kill -9 $PID
    echo "进程已终止。"
else
    echo "未找到占用 8188 端口的进程。"
fi
