#!/bin/bash
for i in {1..65}; do
    echo "========== Processing Lang $i =========="
    # 如果目录已存在，跳过下载（但会重新编译测试）
    if [ ! -d "bugs/Lang$i" ]; then
        ~/defects4j/framework/bin/defects4j checkout -p Lang -v ${i}b -w ~/an-implementation-of-chatrepair/bugs/Lang$i
    fi
    cd ~/an-implementation-of-chatrepair/bugs/Lang$i
    ~/defects4j/framework/bin/defects4j compile
    ~/defects4j/framework/bin/defects4j test
    cd ~/an-implementation-of-chatrepair
done
