projects=("Lang" "Chart" "Closure" "Math" "Mockito" "Time")
for project in "${projects[@]}"
do
    echo "Runing initial chat............."$project""
    python3 src/main.py initial-chat "$project" y
done