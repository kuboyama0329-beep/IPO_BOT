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
import re

app = Flask(__name__)

# LINE Bot設定
LINE_CHANNEL_ACCESS_TOKEN = 'monHF/zzGHwyTnww0TpB+mewCv3r2YVkuXtm6Sns4NtUV37N/vDbMvLdai/n6Qi6rqyxMQ+Xmr2RdwAa0zt5/bgCXwa/5AWal2Ec3ndPcb7m+/u27RIRcjiSYmmaTzaDG/lOExk28Kwubfg+tEKzfQdB04t89/1O/w1cDnyilFU='
LINE_USER_ID = 'U115368062ae933fb88020ea97a1cba8b'

class IPOMonitor:
    def __init__(self):
        # 環境変数からLINE設定を読み込み（GitHub Actions用）
        token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', LINE_CHANNEL_ACCESS_TOKEN)
        self.line_api = LineBotApi(token)
        self.url = "https://www.ipokiso.com/company/index.html"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        self.known_ipos = set()
        self.last_check = None

    def _is_company_table(self, table):
        # 最初の行に『企業名』ヘッダーが1列で存在するテーブル
        ths = table.find_all('th')
        if len(ths) == 1 and '企業名' in ths[0].get_text(strip=True):
            return True
        # 企業名リンクが多数存在し、列が1つだけの行が続く場合
        rows = table.find_all('tr')
        if rows:
            cells_counts = set(len(r.find_all(['td','th'])) for r in rows)
            if cells_counts == {1} and any(r.find('a') for r in rows):
                return True
        return False

    def _is_detail_table(self, table):
        # 『申し込み期間』を含むヘッダーがある
        header = table.find('tr')
        if not header:
            return False
        cells = header.find_all(['th','td'])
        header_text = ''.join(c.get_text(strip=True) for c in cells)
        return '申し込み期間' in header_text or '申込期間' in header_text

    def _parse_company_table(self, table):
        names = []
        for row in table.find_all('tr'):
            cell = row.find(['td','th'])
            if not cell:
                continue
            a = cell.find('a')
            text = (a.get_text(strip=True) if a else cell.get_text(strip=True))
            if text and text != '企業名':
                names.append(text)
        return names

    def _parse_detail_table(self, table):
        # ヘッダー行から列インデックスを特定
        rows = table.find_all('tr')
        header_row = None
        for r in rows:
            if r.find('th') or '申し込み期間' in r.get_text():
                header_row = r
                break
        if not header_row:
            return []
        headers = [c.get_text(strip=True) for c in header_row.find_all(['th','td'])]
        def col(name, alt=None):
            for i,h in enumerate(headers):
                if name in h or (alt and alt in h):
                    return i
            return -1
        idx_period = col('申し込み期間','申込期間')
        idx_listing = col('上場日')
        idx_offering = col('公募価格')
        idx_rating = col('総合評価')
        details = []
        for r in rows[rows.index(header_row)+1:]:
            cells = r.find_all('td')
            if not cells:
                continue
            def get(i):
                return cells[i].get_text(strip=True) if 0<=i<len(cells) else ''
            period = get(idx_period)
            listing = get(idx_listing)
            offering = get(idx_offering)
            rating = get(idx_rating)
            if not rating and 0<=idx_rating<len(cells):
                img = cells[idx_rating].find('img')
                if img and img.get('src'):
                    src = img.get('src')
                    rating = 'S' if 's03' in src else 'A' if 'a03' in src else 'B' if 'b03' in src else 'C' if 'c03' in src else 'D' if 'd03' in src else ''
            details.append({
                'application_period': period,
                'listing_date': listing,
                'offering_price': offering,
                'rating': rating
            })
        return details

    def scrape_ipo_data(self):
        try:
            print(f"[{datetime.now()}] IPOサイトからデータを取得中...")
            response = requests.get(self.url, headers=self.headers, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            tables = soup.find_all('table')
            ipo_list = []
            i = 0
            while i < len(tables):
                t = tables[i]
                if self._is_company_table(t) and i+1 < len(tables) and self._is_detail_table(tables[i+1]):
                    names = self._parse_company_table(t)
                    details = self._parse_detail_table(tables[i+1])
                    n = min(len(names), len(details))
                    for k in range(n):
                        d = details[k]
                        if re.search(r'\d{1,2}/\d{1,2}', d.get('application_period','')):
                            ipo_list.append({
                                'company_name': names[k],
                                'application_period': d['application_period'],
                                'listing_date': d.get('listing_date',''),
                                'offering_price': d.get('offering_price',''),
                                'rating': d.get('rating','')
                            })
                    i += 2
                else:
                    i += 1
            print(f"[{datetime.now()}] {len(ipo_list)}件のIPO情報を取得しました")
            return ipo_list
        except Exception as e:
            print(f"[{datetime.now()}] スクレイピング中にエラーが発生: {e}")
            return []

    def parse_date_range(self, date_range_str):
        try:
            if not date_range_str:
                return None, None
            raw = date_range_str
            s = raw
            s = s.replace('〜', '～').replace('-', '～').replace('–', '～').replace('—', '～')
            s = re.sub(r'\s+', '', s)
            md = re.findall(r'(\d{1,2})\/(\d{1,2})', s)
            if len(md) < 2:
                print(f"[DEBUG] 期間パース失敗: '{raw}' 正規化後: '{s}'")
                return None, None
            (sm, sd), (em, ed) = md[0], md[1]
            current_year = datetime.now().year
            sm, sd, em, ed = int(sm), int(sd), int(em), int(ed)
            start_date = datetime(current_year, sm, sd)
            end_date = datetime(current_year, em, ed)
            if em < sm:
                end_date = datetime(current_year + 1, em, ed)
            return start_date, end_date
        except Exception as e:
            print(f"[DEBUG] 日付解析エラー: '{date_range_str}' -> {e}")
            return None, None

    def is_currently_accepting(self, application_period):
        try:
            start_date, end_date = self.parse_date_range(application_period)
            if start_date and end_date:
                now = datetime.now()
                return start_date <= now <= end_date, start_date, end_date
            return False, None, None
        except Exception as e:
            print(f"申し込み期間判定エラー: {e}")
            return False, None, None

    def send_line_notification(self, ipo_info):
        try:
            message = f"""📈 IPO申し込み期間中のお知らせ 📈

🏢 企業名: {ipo_info['company_name']}
📅 申し込み期間: {ipo_info['application_period']}
📊 上場日: {ipo_info['listing_date']}
💰 公募価格: {ipo_info['offering_price']}
⭐ 総合評価: {ipo_info['rating']}

🔗 詳細: {self.url}

今すぐ申し込みを検討してください！"""
            user_id = os.environ.get('LINE_USER_ID', LINE_USER_ID)
            self.line_api.push_message(user_id, TextSendMessage(text=message))
            print(f"[{datetime.now()}] LINE通知を送信: {ipo_info['company_name']}")
        except Exception as e:
            print(f"[{datetime.now()}] LINE通知送信エラー: {e}")

    def send_daily_summary(self, ipo_list):
        try:
            current_ipos = []
            for ipo in ipo_list:
                ok, sd, ed = self.is_currently_accepting(ipo['application_period'])
                if ok:
                    current_ipos.append(ipo)
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
            user_id = os.environ.get('LINE_USER_ID', LINE_USER_ID)
            self.line_api.push_message(user_id, TextSendMessage(text=message))
            print(f"[{datetime.now()}] 毎日サマリー通知を送信")
        except Exception as e:
            print(f"[{datetime.now()}] サマリー通知送信エラー: {e}")

    def check_and_notify(self):
        try:
            print(f"[{datetime.now()}] IPO情報をチェック中...")
            ipo_list = self.scrape_ipo_data()
            current_ipos = set()
            for ipo in ipo_list:
                ok, sd, ed = self.is_currently_accepting(ipo['application_period'])
                print(f"[DEBUG] {ipo['company_name']} 期間='{ipo['application_period']}' -> 開始={sd} 終了={ed} 判定={ok}")
                if ok:
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
    print(f"[{datetime.now()}] IPO監視BOTを開始しました")
    print(f"[{datetime.now()}] 毎日朝8時に自動チェックを実行します")
    schedule.every().day.at("08:00").do(ipo_monitor.daily_morning_check)
    print(f"[{datetime.now()}] 初回チェックを実行中...")
    ipo_monitor.daily_morning_check()
    while True:
        schedule.run_pending()
        time.sleep(60)

@app.route('/')
def home():
    return jsonify({
        'status': 'running',
        'message': 'IPO監視BOTが動作中です（毎日朝8時チェック）',
        'last_check': ipo_monitor.last_check.isoformat() if ipo_monitor.last_check else None
    })

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'})

@app.route('/check')
def manual_check():
    try:
        ipo_monitor.check_and_notify()
        return jsonify({'status': 'success', 'message': '手動チェック完了'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

if __name__ == '__main__':
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port) 