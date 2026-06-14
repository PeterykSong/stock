@echo off
cd /d D:\git_repo\stock

git pull origin main

git add .
git commit -m "auto update" || echo No changes to commit

git push origin main