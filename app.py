from flask import Flask, render_template, url_for, session, redirect, request
from authlib.integrations.flask_client import OAuth
import os
import requests
import urllib3
import xml.etree.ElementTree as ET
import random
from words_db import basic_words
import json
from datetime import datetime
from werkzeug.middleware.proxy_fix import ProxyFix

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.urandom(24)

RANKING_FILE = 'ranking.json'
RANKING_FILE_CONSONANT = 'ranking_consonant.json'
CHOSUNG_LIST = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']

dictionary_api_key = '7E98638BB1A1278BE9FB408A95D9DF34'

def get_chosung(word):
    result = ""
    for char in word:
        code = ord(char) - 44032
        if 0 <= code <= 11171:
            chosung_index = code // 588
            result += CHOSUNG_LIST[chosung_index]
        else:
            result += char
    return result

def get_ranking_consonant():
    try:
        with open(RANKING_FILE_CONSONANT, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def update_ranking_consonant(name, score):
    ranking = get_ranking_consonant()
    new_record = {
        'name': name,
        'score': score,
        'date': datetime.now().strftime('%Y-%m-%d')
    }
    ranking.append(new_record)
    ranking.sort(key=lambda x: x['score'], reverse=True)
    ranking = ranking[:10]
    
    with open(RANKING_FILE_CONSONANT, 'w', encoding='utf-8') as f:
        json.dump(ranking, f, ensure_ascii=False, indent=4)
    return ranking

def get_ranking():
    try:
        with open(RANKING_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def update_ranking(name, score):
    ranking = get_ranking()
    new_record = {
        'name': name,
        'score': score,
        'date': datetime.now().strftime('%Y-%m-%d')
    }
    ranking.append(new_record)
    ranking.sort(key=lambda x: x['score'], reverse=True)
    ranking = ranking[:10]
    
    with open(RANKING_FILE, 'w', encoding='utf-8') as f:
        json.dump(ranking, f, ensure_ascii=False, indent=4)
    return ranking

game_data_pool = []

if basic_words:
    print("데이터 최적화 중... (초성 변환)")
    for item in basic_words:
        new_item = item.copy()
        new_item['chosung'] = get_chosung(item['word'])
        game_data_pool.append(new_item)
    print("완료!")

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id='960249686982-a99ao2kso93e6d2fhr97gkrlqho8l0kb.apps.googleusercontent.com',
    client_secret='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',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

@app.route('/')
def index():
    user = session.get('user')
    return render_template('index.html', user=user)

@app.route('/search')
def search():
    keyword = request.args.get('q')
    user = session.get('user')

    if not keyword:
        return render_template('index.html', user=user)

    url = "https://stdict.korean.go.kr/api/search.do"
    
    params = {
        'key': dictionary_api_key,
        'q': keyword,
        'req_type': 'xml',
        'advanced': 'y',
        'method': 'exact',
        'num': 10,
        'target': 1
    }

    search_results = []

    try:
        response = requests.get(url, params=params, verify=False, timeout=5)
        
        if response.status_code == 200:
            try:
                root = ET.fromstring(response.content)
                for item in root.findall('item'):
                    word = item.findtext('word')
                    pos = item.findtext('pos')
                    hanja = item.findtext('origin') or '' 
                    
                    sense_list = []
                    for sense in item.findall('sense'):
                        definition = sense.findtext('definition')
                        if definition:
                            definition = definition.strip()
                            sense_list.append({'definition': definition})
                    
                    search_results.append({
                        'word': word,
                        'pos': pos,
                        'hanja': hanja,
                        'sense': sense_list
                    })
                    
            except ET.ParseError:
                print("[ERROR] XML 파싱 실패 (데이터 형식이 올바르지 않음)")

    except Exception as e:
        print(f"[ERROR] 요청 실패: {e}")

    return render_template('search_result.html', 
                           user=user, 
                           keyword=keyword, 
                           results=search_results)

@app.route('/login')
def login():
    redirect_uri = url_for('auth', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/callback')
def auth():
    token = google.authorize_access_token()
    resp = google.get('https://www.googleapis.com/oauth2/v3/userinfo')
    user_info = resp.json()
    session['user'] = user_info
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))

@app.route('/test')
def test_menu():
    user = session.get('user')
    return render_template('test_menu.html', user=user)

@app.route('/test/start/<mode>')
def test_start(mode):
    if not basic_words or len(basic_words) < 10:
        return "단어 데이터가 부족합니다. (최소 10개 필요)"
    
    count = min(len(basic_words), 10)
    selected_questions = random.sample(basic_words, count)
    
    session['quiz'] = {
        'mode': mode,
        'questions': selected_questions,
        'total': count,
        'current_index': 0,
        'score': 0,
        'history': []
    }
    return redirect(url_for('test_play'))

@app.route('/test/play')
def test_play():
    user = session.get('user')
    quiz = session.get('quiz')

    if not quiz or quiz['current_index'] >= quiz['total']:
        return redirect(url_for('test_result'))

    current_q = quiz['questions'][quiz['current_index']]
    
    options = []
    if quiz['mode'] == 'easy':
        distractors = random.sample([w for w in basic_words if w['word'] != current_q['word']], 3)
        options = distractors + [current_q]
        random.shuffle(options)

    return render_template(f"test_{quiz['mode']}.html", 
                           user=user,
                           question=current_q,
                           options=options,
                           index=quiz['current_index'] + 1,
                           total=quiz['total'])

@app.route('/test/check', methods=['POST'])
def test_check():
    quiz = session.get('quiz')
    if not quiz:
        return {'error': '세션 만료'}, 400

    data = request.get_json()
    user_answer = data.get('answer', '').strip()
    
    current_q = quiz['questions'][quiz['current_index']]
    correct_answer = current_q['word']
    
    is_correct = (user_answer == correct_answer)
    
    if is_correct:
        quiz['score'] += 1
    
    quiz['current_index'] += 1
    session['quiz'] = quiz

    return {
        'correct': is_correct,
        'answer': correct_answer,
        'finished': quiz['current_index'] >= quiz['total']
    }

@app.route('/test/result')
def test_result():
    user = session.get('user')
    quiz = session.get('quiz')
    
    if not quiz:
        return redirect(url_for('test_menu'))
    
    score = quiz['score']
    total = quiz['total']
    
    return render_template('test_result.html', user=user, score=score, total=total)

@app.route('/game')
def game_menu():
    user = session.get('user')
    return render_template('game_menu.html', user=user)

@app.route('/game/acid')
def game_acid():
    user = session.get('user')
    
    if not basic_words:
        return "단어 데이터가 없습니다."
    
    sample_count = min(len(basic_words), 150)
    selected_words = random.sample(basic_words, sample_count)
    
    ranking = get_ranking()

    return render_template('game_acid.html', 
                           user=user, 
                           all_words=selected_words,
                           ranking=ranking)

@app.route('/game/acid/score', methods=['POST'])
def game_acid_score():
    user = session.get('user')
    if not user:
        return {'error': '로그인이 필요합니다.'}, 401
        
    data = request.get_json()
    score = data.get('score', 0)
    
    new_ranking = update_ranking(user['name'], score)
    
    return {'ranking': new_ranking}

@app.route('/game/consonant')
def game_consonant():
    user = session.get('user')
    if not game_data_pool:
        return "단어 데이터가 없습니다."
    
    sample_count = min(len(game_data_pool), 100)
    selected_words = random.sample(game_data_pool, sample_count)
        
    ranking = get_ranking_consonant()

    return render_template('game_consonant.html', 
                           user=user, 
                           all_words=selected_words,
                           ranking=ranking)

@app.route('/game/consonant/score', methods=['POST'])
def game_consonant_score():
    user = session.get('user')
    if not user:
        return {'error': '로그인 필요'}, 401
        
    data = request.get_json()
    score = data.get('score', 0)
    
    update_ranking_consonant(user['name'], score)
    return {'success': True}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)