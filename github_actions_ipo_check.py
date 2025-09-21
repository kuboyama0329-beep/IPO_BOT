#!/usr/bin/env python3
"""
GitHub Actions用 IPOチェックスクリプト
毎朝8時に実行される
"""

import os
from app import IPOMonitor

def main():
    print(f"[{os.environ.get('TZ', 'UTC')}] GitHub Actions IPOチェック開始")
    
    # 環境変数から設定を読み込み
    monitor = IPOMonitor()
    
    # 毎日朝8時のチェックを実行
    monitor.daily_morning_check()
    
    print(f"[{os.environ.get('TZ', 'UTC')}] GitHub Actions IPOチェック完了")

if __name__ == '__main__':
    main()
