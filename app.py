#!/usr/bin/env python3
"""
IPO監視BOT - Railway版（毎日朝8時）
"""

import os
import threading
import time
from datetime import datetime
from flask import Flask, jsonify
import requests
from bs4 import BeautifulSoup
import schedule
from linebot import LineBotApi
from linebot.models import TextSendMessage

app = Flask(__name__)

# LINE Bot設定
LINE_CHANNEL_ACCESS_TOKEN = 'monHF/zzGHwyTnww0TpB+mewCv3r2YVkuXtm6Sns4NtUV37N/vDbMvLdai/n6Qi6rqyxMQ+Xmr2RdwAa0zt5/bgCXwa/5AWal2Ec3ndPcb7m+/u27RIRcjiSYmmaTzaDG/lOExk28Kwubfg+tEKzfQdB04t89/1O/w1cDnyilFU='
LINE_USER_ID = 'U115368062ae933fb88020ea97a1cba8b'

class IPOMonitor:
    def __init__(self):
        self.line_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
        self.url = "https://www.ipokiso.com/company/index.html"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        self.known_ipos = set()
        self.last_check = None
        
    def scrape_ipo_data(self):
        """IPOサイトからデータをスクレイピング"""
        try:
            print(f"[{datetime.now()}] IPOサイトからデータを取得中...")
            response = requests.get(self.url, headers=self.headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            ipo_list = []
            
            tables = soup.find_all('table')
            
            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 8:
                        try:
                            company_cell = cells[0]
                            company_link = company_cell.find('a')
                            if company_link:
                                company_name = company_link.get_text(strip=True)
                            else:
                                company_name = company_cell.get_text(strip=True)
                            
                            application_period = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                            listing_date = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                            offering_price = cells[6].get_text(strip=True) if len(cells) > 6 else ""
                            
                            rating_img = cells[0].find('img') if len(cells) > 0 else None
                            rating = ""
                            if rating_img:
                                img_src = rating_img.get('src', '')
                                if 's03.gif' in img_src:
                                    rating = "S"
                                elif 'a03.gif' in img_src:
                                    rating = "A"
                                elif 'b03.gif' in img_src:
                                    rating = "B"
                                elif 'c03.gif' in img_src:
                                    rating = "C"
                                elif 'd03.gif' in img_src:
                                    rating = "D"
                            
                            if company_name and application_period:
                                ipo_info = {
                                    'company_name': company_name,
                                    'application_period': application_period,
                                    'listing_date': listing_date,
                                    'offering_price': offering_price,
                                    'rating': rating
                                }
                                ipo_list.append(ipo_info)
                                
                        except Exception as e:
                            print(f"行の解析中にエラー: {e}")
                            continue
            
            print(f"[{datetime.now()}] {len(ipo_list)}件のIPO情報を取得しました")
            return ipo_list
            
        except Exception as e:
            print(f"[{datetime.now()}] スクレイピング中にエラーが発生: {e}")
            return []
    
    def parse_date_range(self, date_range_str):
        """日付範囲の文字列を解析"""
        try:
            if '～' in date_range_str:
                start_str, end_str = date_range_str.split('～')
                current_year = datetime.now().year
                
                start_parts = start_str.strip().split('/')
                start_month = int(start_parts[0])
                start_day = int(start_parts[1])
                start_date = datetime(current_year, start_month, start_day)
                
                end_parts = end_str.strip().split('/')
                end_month = int(end_parts[0])
                end_day = int(end_parts[1])
                end_date = datetime(current_year, end_month, end_day)
                
                if end_month < start_month:
                    end_date = datetime(current_year + 1, end_month, end_day)
                
                return start_date, end_date
            else:
                return None, None
                
        except Exception as e:
            print(f"日付解析エラー: {date_range_str}, {e}")
            return None, None
    
    def is_currently_accepting(self, application_period):
        """現在が申し込み期間内かどうかを判定"""
        try:
            start_date, end_date = self.parse_date_range(application_period)
            if start_date and end_date:
                now = datetime.now()
                return start_date <= now <= end_date
            return False
        except Exception as e:
            print(f"申し込み期間判定エラー: {e}")
            return False
    
    def send_line_notification(self, ipo_info):
        """LINEにIPO通知を送信"""
        try:
            message = f"""📈 IPO申し込み期間中のお知らせ 📈

🏢 企業名: {ipo_info['company_name']}
📅 申し込み期間: {ipo_info['application_period']}
📊 上場日: {ipo_info['listing_date']}
💰 公募価格: {ipo_info['offering_price']}
⭐ 総合評価: {ipo_info['rating']}

🔗 詳細: {self.url}

今すぐ申し込みを検討してください！"""

            self.line_api.push_message(LINE_USER_ID, TextSendMessage(text=message))
            print(f"[{datetime.now()}] LINE通知を送信: {ipo_info['company_name']}")
            
        except Exception as e:
            print(f"[{datetime.now()}] LINE通知送信エラー: {e}")
    
    def send_daily_summary(self, ipo_list):
        """毎日のサマリー通知を送信"""
        try:
            current_ipos = [ipo for ipo in ipo_list if self.is_currently_accepting(ipo['application_period'])]
            
            if current_ipos:
                message = f"""🌅 おはようございます！

📊 本日のIPO申し込み状況

現在申し込み期間中のIPO: {len(current_ipos)}件

"""
                
                for i, ipo in enumerate(current_ipos[:5], 1):
                    message += f"{i}. {ipo['company_name']}\n"
                    message += f"   期間: {ipo['application_period']}\n"
                    message += f"   価格: {ipo['offering_price']}\n"
                    message += f"   評価: {ipo['rating']}\n\n"
                
                if len(current_ipos) > 5:
                    message += f"... 他 {len(current_ipos) - 5}件\n\n"
                
                message += f"🔗 詳細: {self.url}"
                
            else:
                message = f"""🌅 おはようございます！

📊 本日のIPO申し込み状況

現在申し込み期間中のIPOはありません。

🔗 詳細: {self.url}"""

            self.line_api.push_message(LINE_USER_ID, TextSendMessage(text=message))
            print(f"[{datetime.now()}] 毎日サマリー通知を送信")
            
        except Exception as e:
            print(f"[{datetime.now()}] サマリー通知送信エラー: {e}")
    
    def check_and_notify(self):
        """IPO情報をチェックして通知を送信"""
        try:
            print(f"[{datetime.now()}] IPO情報をチェック中...")
            ipo_list = self.scrape_ipo_data()
            
            current_ipos = set()
            
            for ipo in ipo_list:
                if self.is_currently_accepting(ipo['application_period']):
                    unique_key = f"{ipo['company_name']}_{ipo['application_period']}"
                    current_ipos.add(unique_key)
                    
                    if unique_key not in self.known_ipos:
                        self.send_line_notification(ipo)
                        self.known_ipos.add(unique_key)
            
            expired_ipos = self.known_ipos - current_ipos
            for expired in expired_ipos:
                self.known_ipos.remove(expired)
                print(f"[{datetime.now()}] 申し込み期間終了: {expired}")
            
            print(f"[{datetime.now()}] 現在申し込み期間中のIPO: {len(current_ipos)}件")
            self.last_check = datetime.now()
            
        except Exception as e:
            print(f"[{datetime.now()}] チェック処理中にエラー: {e}")
    
    def daily_morning_check(self):
        """毎日朝8時の定期チェック"""
        print(f"[{datetime.now()}] === 毎日朝8時のIPOチェック開始 ===")
        
        try:
            ipo_list = self.scrape_ipo_data()
            self.send_daily_summary(ipo_list)
            self.check_and_notify()
            
            print(f"[{datetime.now()}] === 毎日朝8時のIPOチェック完了 ===")
            
        except Exception as e:
            print(f"[{datetime.now()}] 毎日チェック中にエラー: {e}")

# グローバル変数
ipo_monitor = IPOMonitor()

def run_scheduler():
    """スケジューラーを実行"""
    print(f"[{datetime.now()}] IPO監視BOTを開始しました")
    print(f"[{datetime.now()}] 毎日朝8時に自動チェックを実行します")
    
    # 毎日朝8時にチェック
    schedule.every().day.at("08:00").do(ipo_monitor.daily_morning_check)
    
    # 初回チェック
    print(f"[{datetime.now()}] 初回チェックを実行中...")
    ipo_monitor.daily_morning_check()
    
    while True:
        schedule.run_pending()
        time.sleep(60)

@app.route('/')
def home():
    """ホームページ"""
    return jsonify({
        'status': 'running',
        'message': 'IPO監視BOTが動作中です（毎日朝8時チェック）',
        'last_check': ipo_monitor.last_check.isoformat() if ipo_monitor.last_check else None
    })

@app.route('/health')
def health():
    """ヘルスチェック"""
    return jsonify({'status': 'healthy'})

@app.route('/check')
def manual_check():
    """手動チェック"""
    try:
        ipo_monitor.check_and_notify()
        return jsonify({'status': 'success', 'message': '手動チェック完了'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

if __name__ == '__main__':
    # スケジューラーを別スレッドで実行
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    # Flaskアプリを起動
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port) 