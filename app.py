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
import importlib.util
import glob
import re

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Serve files from the assets directory as static resources (e.g., logo.png)
app = Flask(__name__, static_folder='assets', static_url_path='/assets')
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.urandom(24)

RANKING_FILE = 'ranking.json'
USER_PROFILE_FILE = 'user_profiles.json'
RANKING_FILE_CONSONANT = 'ranking_consonant.json'
CHOSUNG_LIST = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']

dictionary_api_key = '7E98638BB1A1278BE9FB408A95D9DF34'

# 골든벨 게임 생성 권한을 가진 이메일 목록
ADMIN_EMAILS = [
    '25_lmj0701@dshs.kr',
    '25_kgb0601@dshs.kr'# 여기에 권한자 이메일 추가
]

# 게임 세션 저장소 (메모리)
game_sessions = {}


def load_profiles():
    """저장된 사용자 프로필 불러오기"""
    try:
        with open(USER_PROFILE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_profiles(profiles):
    """사용자 프로필 저장"""
    with open(USER_PROFILE_FILE, 'w', encoding='utf-8') as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)


def add_points(email, points_to_add):
    """사용자에게 포인트를 추가"""
    if not email or points_to_add == 0:
        return

    profiles = load_profiles()
    profile = normalize_profile(profiles.get(email, {}))
    
    profile['points'] = profile.get('points', 0) + points_to_add
    profiles[email] = profile
    
    save_profiles(profiles)
    
    # 세션에 포인트 정보가 있다면 업데이트
    if 'profile' in session and session['profile'] is not None:
        session['profile']['points'] = profile['points']
        session.modified = True



def normalize_profile(profile):
    """프로필 기본값(포인트 등)을 채워서 반환"""
    profile = profile or {}
    if 'points' not in profile:
        profile['points'] = 0
    return profile


def is_profile_complete(profile):
    """학년/반/번호/이름 모두 채워졌는지 확인"""
    required_fields = ['grade', 'class_number', 'student_number', 'name']
    return bool(profile) and all(str(profile.get(field, '')).strip() != '' for field in required_fields)


def is_admin(user):
    """관리자 여부 판별"""
    return user and user.get('email') in ADMIN_EMAILS


def generate_game_code():
    """6자리 랜덤 숫자 코드 생성"""
    while True:
        code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        if code not in game_sessions:
            return code

def load_quiz_sets():
    """quiz_sets 폴더의 모든 문제집을 로드"""
    quiz_sets = []
    quiz_dir = os.path.join(os.path.dirname(__file__), 'quiz_sets')
    
    if not os.path.exists(quiz_dir):
        return quiz_sets
    
    for file_path in glob.glob(os.path.join(quiz_dir, '*.py')):
        if os.path.basename(file_path).startswith('__'):
            continue
            
        try:
            spec = importlib.util.spec_from_file_location("quiz_module", file_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            if hasattr(module, 'questions') and hasattr(module, 'quiz_name'):
                quiz_sets.append({
                    'id': os.path.splitext(os.path.basename(file_path))[0],
                    'name': module.quiz_name,
                    'description': getattr(module, 'quiz_description', ''),
                    'difficulty': getattr(module, 'difficulty', '보통'),
                    'count': len(module.questions),
                    'file': os.path.basename(file_path)
                })
        except Exception as e:
            print(f"[ERROR] 문제집 로드 실패 ({file_path}): {e}")
    
    return quiz_sets

def load_columns():
    """columns 폴더의 모든 칼럼을 로드"""
    columns = []
    columns_dir = os.path.join(os.path.dirname(__file__), 'columns')
    
    if not os.path.exists(columns_dir):
        return columns
    
    for file_path in glob.glob(os.path.join(columns_dir, '*.py')):
        if os.path.basename(file_path).startswith('__'):
            continue
            
        try:
            spec = importlib.util.spec_from_file_location("column_module", file_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            if hasattr(module, 'title') and hasattr(module, 'content'):
                columns.append({
                    'id': getattr(module, 'column_id', os.path.splitext(os.path.basename(file_path))[0]),
                    'title': module.title,
                    'date': getattr(module, 'date', ''),
                    'author': getattr(module, 'author', ''),
                    'preview': module.content[:100] + '...' if len(module.content) > 100 else module.content
                })
        except Exception as e:
            print(f"[ERROR] 칼럼 로드 실패 ({file_path}): {e}")
    
    # 날짜순 정렬 (최신순)
    columns.sort(key=lambda x: x['id'], reverse=True)
    
    return columns

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


@app.context_processor
def inject_user_profile():
    """모든 템플릿에 사용자/프로필 정보 전달"""
    current_user = session.get('user')
    return {
        'user': current_user,
        'profile': session.get('profile'),
        'is_admin_user': is_admin(current_user)
    }


@app.route('/')
def index():
    user = session.get('user')
    if user:
        print(f"[DEBUG] 현재 로그인된 이메일: {user.get('email')}")
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

    # 학교 도메인 검사 (@dshs.kr)
    email = user_info.get('email', '')
    if not email.endswith('@dshs.kr'):
        session.clear()
        return "학교 이메일(@dshs.kr) 계정만 로그인할 수 있습니다.", 403

    session['user'] = user_info

    profiles = load_profiles()
    profile = normalize_profile(profiles.get(email, {}) if email else {})

    if profile and profile.get('name'):
        session['user']['name'] = profile['name']

    if profile:
        session['profile'] = profile
    else:
        session.pop('profile', None)

    if not is_profile_complete(profile):
        return redirect(url_for('signup'))

    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('profile', None)
    return redirect(url_for('index'))


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """구글 로그인 후 학년/반/번호/이름을 등록"""
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))

    email = user.get('email')
    profiles = load_profiles()
    stored_profile = normalize_profile(profiles.get(email, {}) if email else {})

    # GET 요청 시 기본값으로 채울 데이터
    profile_form = stored_profile.copy()
    errors = []

    if request.method == 'POST':
        profile_form['grade'] = request.form.get('grade', '').strip()
        profile_form['class_number'] = request.form.get('class_number', '').strip()
        profile_form['student_number'] = request.form.get('student_number', '').strip()
        profile_form['name'] = request.form.get('name', '').strip()

        if not email:
            errors.append('구글 계정 이메일을 찾을 수 없습니다. 다시 로그인해주세요.')

        # 학년 검증 (1~6 자유롭게)
        try:
            grade_val = int(profile_form['grade'])
            if grade_val < 1 or grade_val > 6:
                errors.append('학년은 1~6 사이 숫자로 입력해주세요.')
        except ValueError:
            errors.append('학년은 숫자로 입력해주세요.')

        # 반 검증 (1~10)
        try:
            class_val = int(profile_form['class_number'])
            if class_val < 1 or class_val > 10:
                errors.append('반은 1~10 사이 숫자로 입력해주세요.')
        except ValueError:
            errors.append('반은 숫자로 입력해주세요.')

        # 번호 검증 (1~50)
        try:
            number_val = int(profile_form['student_number'])
            if number_val < 1 or number_val > 50:
                errors.append('번호는 1~50 사이 숫자로 입력해주세요.')
        except ValueError:
            errors.append('번호는 숫자로 입력해주세요.')

        if not profile_form['name']:
            errors.append('이름을 입력해주세요.')

        if not errors:
            new_profile = {
                'grade': grade_val,
                'class_number': class_val,
                'student_number': number_val,
                'name': profile_form['name'],
                'points': stored_profile.get('points', 0)
            }
            profiles[email] = new_profile
            save_profiles(profiles)

            # 세션 최신화
            session['profile'] = new_profile
            session['user']['name'] = new_profile['name']

            return redirect(url_for('index'))

    return render_template('signup.html', user=user, profile=profile_form, errors=errors)


@app.route('/mypage')
def mypage():
    """로그인 사용자의 프로필을 보는 전용 페이지"""
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))

    email = user.get('email')
    profiles = load_profiles()
    profile = normalize_profile(profiles.get(email, {}) if email else {})

    if not is_profile_complete(profile):
        return redirect(url_for('signup'))

    return render_template('mypage.html', user=user, profile=profile)

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
    points_earned = score * 10
    
    if user and points_earned > 0:
        add_points(user.get('email'), points_earned)
    
    # 세션에서 퀴즈 정보 삭제
    session.pop('quiz', None)
    
    return render_template('test_result.html', user=user, score=score, total=total, points_earned=points_earned)

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
    
    # 포인트 지급 (점수/10)
    points_to_add = int(score / 10)
    if points_to_add > 0:
        add_points(user.get('email'), points_to_add)
    
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
    
    # 포인트 지급 (점수/10)
    points_to_add = int(score / 10)
    if points_to_add > 0:
        add_points(user.get('email'), points_to_add)
    
    update_ranking_consonant(user['name'], score)
    return {'success': True}

@app.route('/game/goldbell')
def game_goldbell():
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))
    
    # 권한 체크: 게임 생성 가능 여부
    can_create = user.get('email') in ADMIN_EMAILS
    
    return render_template('game_goldbell.html', user=user, can_create=can_create)

@app.route('/game/goldbell/create')
def game_goldbell_create():
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))
    
    # 권한 체크
    if user.get('email') not in ADMIN_EMAILS:
        return redirect(url_for('game_goldbell'))
    
    # 모든 문제집 로드
    quiz_sets = load_quiz_sets()
    
    return render_template('game_goldbell_create.html', user=user, quiz_sets=quiz_sets)

@app.route('/game/goldbell/save-quiz', methods=['POST'])
def save_quiz():
    user = session.get('user')
    if not user or user.get('email') not in ADMIN_EMAILS:
        return {'error': '권한이 없습니다.'}, 403
    
    try:
        data = request.get_json()
        quiz_name = data.get('quiz_name', '').strip()
        quiz_description = data.get('quiz_description', '').strip()
        difficulty = data.get('difficulty', '보통')
        questions = data.get('questions', [])
        
        if not quiz_name:
            return {'error': '문제집 이름이 필요합니다.'}, 400
        
        if not questions or len(questions) == 0:
            return {'error': '최소 1개 이상의 문제가 필요합니다.'}, 400
        
        # 파일명 생성 (공백을 언더스코어로, 특수문자 제거)
        file_id = re.sub(r'[^\w\s-]', '', quiz_name.lower())
        file_id = re.sub(r'[-\s]+', '_', file_id)
        
        # 중복 방지
        quiz_dir = os.path.join(os.path.dirname(__file__), 'quiz_sets')
        file_path = os.path.join(quiz_dir, f'{file_id}.py')
        counter = 1
        while os.path.exists(file_path):
            file_path = os.path.join(quiz_dir, f'{file_id}_{counter}.py')
            counter += 1
        
        # 파일 내용 생성
        def escape_text(value):
            return (value or "").replace("\\", "\\\\").replace('"', '\\"')
        
        file_content = f"""# -*- coding: utf-8 -*-
\"\"\"
{quiz_name}
난이도: {difficulty}
\"\"\"

quiz_name = "{escape_text(quiz_name)}"
quiz_description = "{escape_text(quiz_description)}"
difficulty = "{escape_text(difficulty)}"

questions = [
"""
        
        for q in questions:
            file_content += f"""    {{
        "question": "{escape_text(q.get('question'))}",
        "explanation": "{escape_text(q.get('explanation', ''))}",
        "answer": "{escape_text(q.get('answer'))}",
        "wrong1": "{escape_text(q.get('wrong1'))}",
        "wrong2": "{escape_text(q.get('wrong2'))}",
        "wrong3": "{escape_text(q.get('wrong3'))}"
    }},
"""
        
        file_content += """]
"""
        
        # 파일 저장
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(file_content)
        
        return {'success': True, 'message': '문제집이 저장되었습니다.', 'file': os.path.basename(file_path)}
        
    except Exception as e:
        print(f"[ERROR] 문제집 저장 실패: {e}")
        return {'error': str(e)}, 500

@app.route('/game/goldbell/start', methods=['POST'])
def start_goldbell_game():
    user = session.get('user')
    if not user or user.get('email') not in ADMIN_EMAILS:
        return {'error': '권한이 없습니다.'}, 403
    
    try:
        data = request.get_json()
        quiz_id = data.get('quiz_id')
        
        if not quiz_id:
            return {'error': '문제집을 선택해주세요.'}, 400
        
        # 문제집 로드
        quiz_dir = os.path.join(os.path.dirname(__file__), 'quiz_sets')
        quiz_file = os.path.join(quiz_dir, f'{quiz_id}.py')
        
        if not os.path.exists(quiz_file):
            return {'error': '문제집을 찾을 수 없습니다.'}, 404
        
        spec = importlib.util.spec_from_file_location("quiz_module", quiz_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        if not hasattr(module, 'questions'):
            return {'error': '문제집 형식이 올바르지 않습니다.'}, 400
        
        # 문제 순서 랜덤 셔플 + 해설 기본값 보강
        questions = [dict(q) for q in module.questions]
        for q in questions:
            q.setdefault('explanation', '')
        random.shuffle(questions)
        
        # 게임 코드 생성
        game_code = generate_game_code()
        
        # 게임 세션 생성
        game_sessions[game_code] = {
            'code': game_code,
            'host': user.get('name'),
            'host_email': user.get('email'),
            'quiz_id': quiz_id,
            'quiz_name': getattr(module, 'quiz_name', quiz_id),
            'questions': questions,
            'players': [],
            'status': 'waiting',  # waiting, intro, playing, finished
            'current_question': -1,  # -1: 시작 전, 0~: 문제 번호
            'question_start_time': None,
            'answers': {},  # {question_index: {player_name: {answer, time, correct, score}}}
            'created_at': datetime.now().isoformat()
        }
        
        return {'success': True, 'game_code': game_code}
        
    except Exception as e:
        print(f"[ERROR] 게임 생성 실패: {e}")
        return {'error': str(e)}, 500

@app.route('/game/goldbell/begin/<game_code>', methods=['POST'])
def begin_goldbell_game(game_code):
    user = session.get('user')
    if not user:
        return {'error': '로그인이 필요합니다.'}, 401
    
    if game_code not in game_sessions:
        return {'error': '게임을 찾을 수 없습니다.'}, 404
    
    game = game_sessions[game_code]
    
    # 호스트 권한 체크
    if game['host_email'] != user.get('email'):
        return {'error': '호스트만 게임을 시작할 수 있습니다.'}, 403
    
    if game['status'] != 'waiting':
        return {'error': '이미 시작된 게임입니다.'}, 400
    
    # 게임 시작
    game['status'] = 'intro'
    
    return {'success': True}

@app.route('/game/goldbell/next/<game_code>', methods=['POST'])
def next_question(game_code):
    user = session.get('user')
    if not user:
        return {'error': '로그인이 필요합니다.'}, 401
    
    if game_code not in game_sessions:
        return {'error': '게임을 찾을 수 없습니다.'}, 404
    
    game = game_sessions[game_code]
    
    # 호스트 권한 체크
    if game['host_email'] != user.get('email'):
        return {'error': '호스트만 제어할 수 있습니다.'}, 403
    
    game['current_question'] += 1
    
    if game['current_question'] >= len(game['questions']):
        game['status'] = 'finished'
        return {'success': True, 'finished': True}
    
    game['status'] = 'playing'
    game['question_start_time'] = datetime.now().isoformat()
    
    return {'success': True, 'question_index': game['current_question']}

@app.route('/game/goldbell/host/<game_code>')
def goldbell_host(game_code):
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))
    
    if game_code not in game_sessions:
        return "게임을 찾을 수 없습니다.", 404
    
    game = game_sessions[game_code]
    
    # 호스트 권한 체크
    if game['host_email'] != user.get('email'):
        return "호스트만 접근할 수 있습니다.", 403
    
    return render_template('game_goldbell_host.html', user=user, game=game)

@app.route('/game/goldbell/join', methods=['POST'])
def join_goldbell_game():
    user = session.get('user')
    if not user:
        return {'error': '로그인이 필요합니다.'}, 401
    
    try:
        data = request.get_json()
        game_code = data.get('code', '').strip()
        
        if not game_code:
            return {'error': '게임 코드를 입력해주세요.'}, 400
        
        if game_code not in game_sessions:
            return {'error': '존재하지 않는 게임 코드입니다.'}, 404
        
        game = game_sessions[game_code]
        
        if game['status'] != 'waiting':
            return {'error': '이미 시작된 게임입니다.'}, 400
        
        # 중복 참여 체크
        player_names = [p['name'] for p in game['players']]
        if user.get('name') in player_names:
            return {'error': '이미 참여한 게임입니다.'}, 400
        
        # 플레이어 추가
        game['players'].append({
            'name': user.get('name'),
            'email': user.get('email'),
            'picture': user.get('picture'),
            'score': 0,
            'joined_at': datetime.now().isoformat()
        })
        
        return {'success': True, 'game_code': game_code}
        
    except Exception as e:
        print(f"[ERROR] 게임 참여 실패: {e}")
        return {'error': str(e)}, 500

@app.route('/game/goldbell/player/<game_code>')
def goldbell_player(game_code):
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))
    
    if game_code not in game_sessions:
        return "게임을 찾을 수 없습니다.", 404
    
    game = game_sessions[game_code]
    
    # 참여자 확인
    player_names = [p['name'] for p in game['players']]
    if user.get('name') not in player_names:
        return "게임에 참여하지 않았습니다.", 403
    
    # 게임이 진행 중이면 선택지 랜덤 배치
    shuffled_choices = None
    if game['status'] == 'playing' and game['current_question'] >= 0:
        question = game['questions'][game['current_question']]
        choices = [
            {'text': question['answer'], 'color': 'red', 'is_answer': True},
            {'text': question['wrong1'], 'color': 'blue', 'is_answer': False},
            {'text': question['wrong2'], 'color': 'yellow', 'is_answer': False},
            {'text': question['wrong3'], 'color': 'green', 'is_answer': False}
        ]
        shuffled_choices = random.sample(choices, len(choices))
    
    return render_template('game_goldbell_player.html', user=user, game=game, shuffled_choices=shuffled_choices)

@app.route('/game/goldbell/submit/<game_code>', methods=['POST'])
def submit_answer(game_code):
    user = session.get('user')
    if not user:
        return {'error': '로그인이 필요합니다.'}, 401
    
    if game_code not in game_sessions:
        return {'error': '게임을 찾을 수 없습니다.'}, 404
    
    game = game_sessions[game_code]
    
    # 참여자 확인
    player_names = [p['name'] for p in game['players']]
    if user.get('name') not in player_names:
        return {'error': '게임에 참여하지 않았습니다.'}, 403
    
    try:
        data = request.get_json()
        answer = data.get('answer')
        
        if game['status'] != 'playing':
            return {'error': '현재 답변을 받을 수 없습니다.'}, 400
        
        question_index = game['current_question']
        question = game['questions'][question_index]
        
        # 이미 답변했는지 체크
        if question_index not in game['answers']:
            game['answers'][question_index] = {}
        
        if user.get('name') in game['answers'][question_index]:
            return {'error': '이미 답변했습니다.'}, 400
        
        # 답변 시간 계산
        start_time = datetime.fromisoformat(game['question_start_time'])
        answer_time = datetime.now()
        time_taken = (answer_time - start_time).total_seconds()
        
        # 정답 확인
        correct = (answer == question['answer'])
        
        # 점수 계산 (정답이면 시간에 따라 500~1000점, 틀리면 0점)
        score = 0
        if correct:
            # 빠를수록 높은 점수 (0초: 1000점, 30초 이상: 500점)
            if time_taken <= 1:
                score = 1000
            elif time_taken >= 30:
                score = 500
            else:
                # 선형 감소: 1000 - (시간 * 500/30)
                score = int(1000 - (time_taken - 1) * (500 / 29))
        
        # 답변 저장
        game['answers'][question_index][user.get('name')] = {
            'answer': answer,
            'time': time_taken,
            'correct': correct,
            'score': score,
            'submitted_at': answer_time.isoformat()
        }
        
        # 플레이어 총점 업데이트
        for player in game['players']:
            if player['name'] == user.get('name'):
                player['score'] += score
                break
        
        return {
            'success': True,
            'correct': correct,
            'score': score,
            'correct_answer': question['answer'],
            'explanation': question.get('explanation', '')
        }
        
    except Exception as e:
        print(f"[ERROR] 답변 제출 실패: {e}")
        return {'error': str(e)}, 500

@app.route('/game/goldbell/status/<game_code>')
def game_status(game_code):
    """게임 상태 조회 (폴링용)"""
    if game_code not in game_sessions:
        return {'error': '게임을 찾을 수 없습니다.'}, 404
    
    game = game_sessions[game_code]
    
    return {
        'status': game['status'],
        'current_question': game['current_question'],
        'total_questions': len(game['questions']),
        'player_count': len(game['players'])
    }


@app.route('/column/new', methods=['GET', 'POST'])
def column_create():
    """관리자 칼럼 등록"""
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))
    if not is_admin(user):
        return "관리자만 접근할 수 있습니다.", 403

    errors = []
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        content = (request.form.get('content') or '').strip()
        quiz_data_raw = request.form.get('quiz_data') or '[]'

        try:
            questions = json.loads(quiz_data_raw)
        except json.JSONDecodeError:
            questions = []
            errors.append('퀴즈 데이터가 올바르지 않습니다.')

        if not title:
            errors.append('제목을 입력해주세요.')
        if not content:
            errors.append('본문을 입력해주세요.')
        if not questions:
            errors.append('퀴즈를 최소 1개 이상 등록해주세요.')

        # 퀴즈 검증
        validated_questions = []
        for idx, q in enumerate(questions):
            question_text = (q.get('question') or '').strip()
            choices = q.get('choices') or []
            answer = q.get('answer')

            if not question_text:
                errors.append(f'{idx + 1}번 문항 질문을 입력해주세요.')
                continue
            if not isinstance(choices, list) or len(choices) < 2:
                errors.append(f'{idx + 1}번 문항 보기를 2개 이상 입력해주세요.')
                continue
            if not isinstance(answer, int) or not (0 <= answer < len(choices)):
                errors.append(f'{idx + 1}번 문항 정답을 올바르게 선택해주세요.')
                continue

            validated_questions.append({
                'question': question_text,
                'choices': choices,
                'answer': answer,
                'explanation': q.get('explanation', '')
            })

        if not errors:
            columns_dir = os.path.join(os.path.dirname(__file__), 'columns')
            os.makedirs(columns_dir, exist_ok=True)

            slug = re.sub(r'[^0-9a-zA-Z가-힣]+', '_', title).strip('_').lower()
            if not slug:
                slug = 'column'
            base_id = datetime.now().strftime('%Y_%m_%d_') + slug
            column_id = base_id
            counter = 1
            while os.path.exists(os.path.join(columns_dir, f'{column_id}.py')):
                column_id = f"{base_id}_{counter}"
                counter += 1

            file_path = os.path.join(columns_dir, f'{column_id}.py')
            safe_title = title.replace('"', '\\"')
            safe_author = (user.get('name') or user.get('email') or '관리자').replace('"', '\\"')
            safe_content = content.replace('"""', '\\"""')

            file_body = f'''# -*- coding: utf-8 -*-
column_id = "{column_id}"
title = "{safe_title}"
date = "{datetime.now().strftime('%Y-%m-%d')}"
author = "{safe_author}"

content = """{safe_content}"""

questions = {json.dumps(validated_questions, ensure_ascii=False, indent=4)}
'''
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(file_body)

            return redirect(url_for('column_detail', column_id=column_id))

    return render_template('column_new.html', user=user, errors=errors)


@app.route('/column')
def column_list():
    user = session.get('user')
    columns = load_columns()
    return render_template('column_list.html', user=user, columns=columns)

@app.route('/column/<column_id>')
def column_detail(column_id):
    user = session.get('user')
    
    # 칼럼 로드
    columns_dir = os.path.join(os.path.dirname(__file__), 'columns')
    column_file = os.path.join(columns_dir, f'{column_id}.py')
    
    if not os.path.exists(column_file):
        return "칼럼을 찾을 수 없습니다.", 404
    
    try:
        spec = importlib.util.spec_from_file_location("column_module", column_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        column = {
            'id': column_id,
            'title': module.title,
            'date': getattr(module, 'date', ''),
            'author': getattr(module, 'author', ''),
            'content': module.content,
            'questions': module.questions
        }
        
        return render_template('column_detail.html', user=user, column=column)
        
    except Exception as e:
        print(f"[ERROR] 칼럼 로드 실패: {e}")
        return "칼럼을 불러올 수 없습니다.", 500

@app.route('/column/submit', methods=['POST'])
def column_submit():
    """칼럼 퀴즈 정답 체크"""
    user = session.get('user')

    try:
        data = request.get_json()
        column_id = data.get('column_id')
        user_answers = data.get('answers', [])  # [0, 2, 1] 형태
        
        # 칼럼 로드
        columns_dir = os.path.join(os.path.dirname(__file__), 'columns')
        column_file = os.path.join(columns_dir, f'{column_id}.py')
        
        if not os.path.exists(column_file):
            return {'error': '칼럼을 찾을 수 없습니다.'}, 404
        
        spec = importlib.util.spec_from_file_location("column_module", column_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        questions = module.questions
        
        # 정답 체크
        correct_count = 0
        wrong_count = 0
        details = []
        
        for i, question in enumerate(questions):
            user_answer_idx = user_answers[i] if i < len(user_answers) else -1
            correct_answer_idx = question['answer']
            
            is_correct = (user_answer_idx == correct_answer_idx)
            
            if is_correct:
                correct_count += 1
            else:
                wrong_count += 1
            
            details.append({
                'is_correct': is_correct,
                'correct_answer': question['choices'][correct_answer_idx],
                'user_answer': question['choices'][user_answer_idx] if 0 <= user_answer_idx < len(question['choices']) else '선택 안 함',
                'explanation': question.get('explanation', '')
            })

        # 포인트 지급 (정답당 20점)
        points_earned = correct_count * 20
        if user and points_earned > 0:
            add_points(user.get('email'), points_earned)
        
        return {
            'total': len(questions),
            'correct': correct_count,
            'wrong': wrong_count,
            'details': details,
            'points_earned': points_earned
        }
        
    except Exception as e:
        print(f"[ERROR] 정답 체크 실패: {e}")
        return {'error': str(e)}, 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
