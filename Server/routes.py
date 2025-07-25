from flask import Blueprint, request, jsonify
from flask_socketio import SocketIO
import models as md
import random
import numpy as np
import joblib
from sklearn.preprocessing import MinMaxScaler
import tensorflow as tf
from tensorflow.keras.utils import CustomObjectScope
import tensorflow.keras.backend as K
from datetime import datetime,timezone,timedelta
from dateutil import parser


bp = Blueprint('routes', __name__)

CMD_TEMP = "NORMAL"
CMD_HUMI = "NORMAL"
CMD_CO2 = "NORMAL"
CMD_LIGHT = "NORMAL"


# utc->kst변환
def parse_log_time(log_time_str):
    dt = parser.parse(log_time_str)    # 자동 포맷 인식
    if dt.tzinfo is None:
        # 만약 tz가 없으면(로컬타임) → UTC로 가정 (필요에 따라 변경)
        dt = dt.replace(tzinfo=timezone.utc)
    # KST로 변환
    return dt.astimezone(timezone(timedelta(hours=9)))

def weighted_loss(y_true, y_pred):
    weight = np.linspace(0.5, 1.5, num=y_true.shape[1])  # 마지막 값에 더 큰 가중치
    return K.mean(weight * K.square(y_pred - y_true))

def range_filter(current,prev,min_val,max_val):
    if current is None:
        return prev
    if current < min_val or current > max_val:
        return prev
    return current
try:
    
    with CustomObjectScope({'weighted_loss': weighted_loss}):
        co2_model =  tf.keras.models.load_model('training/CO2.h5')
    temp_model = tf.keras.models.load_model('./training/Temperature.h5')
    temp_scaler = joblib.load('./training/Temperature.pkl')
    humi_model = tf.keras.models.load_model('./training/humidity.h5')
    humi_scaler = joblib.load('./training/humidity.pkl')
    co2_model = tf.keras.models.load_model('./training/CO2.h5')
    co2_scaler = joblib.load('./training/CO2.pkl')

except Exception as e:
    print("모델 또는 스케일러 로드 실패:", e)
    temp_model = None
    temp_scaler = None
    humi_model = None
    humi_scaler = None
    co2_model = None
    co2_scaler = None


def check_cmd(cmd):
    if(cmd=="INCREASE"):
        return 0
    elif cmd=="NORMAL":
        return 1
    else:
        return 2
    
#테스트용 코드 구분
# 연속성을 가진 테스트 데이터 저장
@bp.route('/test/temp/insert')
def temps():
    base_temp = 20.0  # 기준 온도 (예: 20도)

    
    for _ in range(30):
        # 이전 온도에서 -2도 ~ +2도 사이 변화 추가
        change = np.random.uniform(-2, 2)
        base_temp = base_temp + change
        
        # 온도 범위를 10~35도로 제한 (극단값 방지)
        base_temp = max(10, min(35,base_temp))

        entry = md.testData(
            temp = round(base_temp, 2),
            humi = round(random.uniform(50, 90), 2),
            co2 = 0,
            light = random.randint(1000,6000)
            
        )
        md.db.session.add(entry)
    md.db.session.commit();
    return jsonify({'message': '테스트 저장 성공'})

@bp.route('/test/co2/insert')
def ts():
    a=0
    dt=400
    for i in range(50):
        dt = dt+a;
        a = random.randint(1,30);
        entry = md.testData(
            temp = round(random.uniform(15, 30), 2),
            humi = round(random.uniform(50, 90), 2),
            co2 = dt,
            light = random.randint(1000,6000)
            
        )
        md.db.session.add(entry)
    md.db.session.commit();
    return jsonify({'message': '테스트 저장 성공'})
        
# 테스트 데이터 예측 현재 온도, co2만 만들어 놓음
@bp.route('/test/predict/temp',methods=['POST'])
def pred_temp():
    if temp_model is None or temp_scaler is None:
       return jsonify({"error": "모델 또는 스케일러가 로드되지 않았습니다."}), 500

    sub = (
        md.testData.query
        .with_entities(md.testData.temp,md.testData.id)
        .order_by(md.testData.id.desc())
        .limit(30)
        
    ).subquery()
    
    rows = (
        md.db.session.query(sub.c.temp,sub.c.id)
        .order_by(sub.c.id)
        .all()
        )
    
    temps = [t for t,_ in rows]
    prev = temps[0]
    filtered_temps = []
    for t in temps:
        filtered = range_filter(t,prev,5.0,40.0)
        filtered_temps.append(filtered)
        prev = filtered
        
    
    filtered_temps = np.array(filtered_temps).reshape(-1, 1)
    temp_scaled = temp_scaler.transform(filtered_temps) 

    # 6. LSTM 입력 형태 맞추기
    X_input = temp_scaled.reshape(1, 30, 1)

    # 7. 예측
    y_pred_scaled = temp_model.predict(X_input)

    # 8. 역변환
    y_pred = temp_scaler.inverse_transform(y_pred_scaled)
    print(f"예측된 다음 시점 온도: {y_pred[0][0]:.2f} ℃")
    return jsonify({
        "temp" : f"현재 저장된 10개의 온도 값: {filtered_temps}",
        "predict": f"{y_pred[0][0]:.2f}"
        })

@bp.route('/test/predict/humi',methods=['POST'])
def pred_humi():
    if humi_model is None or humi_scaler is None:
       return jsonify({"error": "모델 또는 스케일러가 로드되지 않았습니다."}), 500

    sub = (
        md.testData.query
        .with_entities(md.testData.humi,md.testData.id)
        .order_by(md.testData.id.desc())
        .limit(30)
        
        
    ).subquery()
    
    rows = (
        md.db.session.query(sub.c.humi,sub.c.id)
        .order_by(sub.c.id)
        .all()
        )
    
    humis = [t for t,_ in rows]
    prev = humis[0]
    filtered_humis = []
    for t in humis:
        filtered = range_filter(t,prev,5.0,40.0)
        filtered_humis.append(filtered)
        prev = filtered
        
    
    filtered_humis = np.array(filtered_humis).reshape(-1, 1)
    humi_scaled = humi_scaler.transform(filtered_humis) 

    # 6. LSTM 입력 형태 맞추기
    X_input = humi_scaled.reshape(1, 30, 1)

    # 7. 예측
    y_pred_scaled = humi_model.predict(X_input)

    # 8. 역변환
    y_pred = humi_scaler.inverse_transform(y_pred_scaled)

    return jsonify({
        "humi" : f"현재 저장된 10개의 습도 값: {humis}",
        "predict": f"{y_pred[0][0]:.2f}",

        })


@bp.route('/test/predict/co2',methods=['POST'])
def pred_co2():
    if co2_model is None or co2_scaler is None:
       return jsonify({"error": "모델 또는 스케일러가 로드되지 않았습니다."}), 500

    sub = (
        md.testData.query
        .with_entities(md.testData.co2,md.testData.id)
        .order_by(md.testData.id.desc())
        .limit(30)
        
    ).subquery()
    
    rows = (
        md.db.session.query(sub.c.co2,sub.c.id)
        #.order_by(sub.c.id)
        .all()
        )
    co2s = [t for t,_ in rows]
    prev = co2s[0]
    filtered_co2s = []
    for t in co2s:
        filtered = range_filter(t,prev,5.0,40.0)
        filtered_co2s.append(filtered)
        prev = filtered
        
    
    filtered_co2s = np.array(filtered_co2s).reshape(-1, 1)
    co2_scaled = co2_scaler.transform(filtered_co2s) 

    # 6. LSTM 입력 형태 맞추기
    X_input = co2_scaled.reshape(1, 30, 1)

    # 7. 예측
    y_pred_scaled = co2_model.predict(X_input)

    # 8. 역변환
    y_pred = co2_scaler.inverse_transform(y_pred_scaled)
    print(f"예측된 다음 시점 co2: {y_pred[0][0]:.2f} ppm")
    return jsonify({
        "co2" : f"{co2s}",
        "predict": f"{y_pred[0][0]:.2f}"
        })


    
#테스트용 코드 구분
@bp.route('/init-db')
def init_db():
    md.db.create_all()
    return "✅ DB 초기화 완료"





@bp.route('/record_data/data_sensor_load',methods=['POST'])
def return_data():
    last_record = (
        md.record_data.query
        .order_by(md.record_data.No.desc())
        .first()
    )
    print(f"cmd_light: {last_record.cmd_light}")
    print(f"cmd_fan: {last_record.cmd_fan}")
    print(f"cmd_temp_peltier: {last_record.cmd_temp_peltier}")
    print(f"cmd_co2_vent: {last_record.cmd_co2_vent}")
    last_record.cmd_fan = check_cmd(last_record.cmd_fan)
    last_record.cmd_light = check_cmd(last_record.cmd_light)
    last_record.cmd_co2_vent = check_cmd(last_record.cmd_co2_vent)
    last_record.cmd_temp_peltier = check_cmd(last_record.cmd_temp_peltier)
        
    record = last_record.to_dict()
    return jsonify(record), 200
    
    
@bp.route('/record_access/test_insert',methods=['POST'])
def access_insert():
    data = request.json
    entry = md.record_access(
        access_time = data['access_time']
        )
    md.db.session.add(entry)
    md.db.session.commit();
    return jsonify({'message': 'Pass'})
@bp.route('/position/insert',methods=['POST'])
def posi_insert():
    data = request.json
    entry = md.record_access(
        product_posi = data['product_posi'],
        status = data['status']
        )
    md.db.session.add(entry)
    md.db.session.commit();
    return jsonify({'message': '위치 저장 성공'})
'''



@bp.route('/insert', methods=['POST'])
def insert_data():
    data = request.json
    entry = testData(
        email=data['email'],
        pwd=data['pwd']
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify({'message': '삽입 성공'})

@bp.route('/data', methods=['GET'])
def get_all():
    rows = testData.query.all()
    return jsonify([
        {
            'id': r.id,
            'email': r.email,
            'pwd': r.pwd
        } for r in rows
    ])

@bp.route('/data/<int:data_id>', methods=['PUT'])
def update_data(data_id):
    data = request.json
    entry = testData.query.get(data_id)
    if entry:
        entry.email = data['email']
        entry.pwd = data['pwd']
        db.session.commit()
        return jsonify({'message': '수정 완료'})
    return jsonify({'message': '데이터 없음'}), 404

@bp.route('/data/<int:data_id>', methods=['DELETE'])
def delete_data(data_id):
    entry = testData.query.get(data_id)
    if entry:
        db.session.delete(entry)
        db.session.commit()
        return jsonify({'message': '삭제 완료'})
    return jsonify({'message': '데이터 없음'}), 404
'''