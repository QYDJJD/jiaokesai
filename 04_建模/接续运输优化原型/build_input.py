"""Create an explicitly synthetic model card linked to a real event."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
CARD = ROOT / '03_情景库/模型输入卡-虹桥降雪背景.json'


def make_card():
    return {
        'schema_version': 'OPT-CARD-01',
        'scenario_id': 'SYN-HQ-SNOW-OPT-01',
        'record_kind': '真实事件背景下的合成模型卡，不计新增真实事件',
        'event_background': {
            'source_url': 'https://jtw.sh.gov.cn/xydt/20231226/6f4ed792491949fb871c7237e4d636ff.html',
            'source_title': '市交通委指挥中心全力做好虹桥火车站夜间大客流疏散交通保障工作',
            'facts': {'event_date': '2023-12-14', 'affected_trains': 28,
                      'affected_passengers': 10008, 'reported_window': '23:00至次日05:00',
                      'actual_bus_trips': 20, 'actual_bus_passenger_trips': 32,
                      'actual_metro_extra_trips': 3, 'actual_metro_passenger_trips': 273,
                      'reported_completion': '2023-12-15T05:10:00+08:00'},
            'not_identified': ['真实接续人数及分时分方向需求', '真实可调车辆和周转',
                               '真实剩余能力、空间阈值、成本及舒适参数'],
        },
        'parameter_evidence': {
            'all_model_numbers': '下列数值均为声明假设；不是历史数据校准或当年排班回放',
            'bus_trip_limit': '20班参照报道规模设为研究上限；不表示取得原排班或20辆车',
            'lead_time': '假设21:28决策、当时预计23:00首批进入，相差92分钟；不是实测预警提前量',
            'comfort': '站立密度和站立人分钟参照文献结构，数值为研究政策参数；不代表满意度',
            'cost': '增量预约费用的合成单价，单位元；不是虹桥合同价或旅客票价',
        },
        'five_dimensions': {
            'information_lead_minutes': 92,
            'arrival_uncertainty': '均匀、前段、中段、后段集中四个允许过程，无发生概率',
            'entry_duration_minutes': 360,
            'new_onward_passengers': 6000,
            'service_state': '基础地面服务可用；公交、增援出租有准备和结束窗口；地铁事实保留但不赋未知容量',
        },
        'parameters': {
            'start_time': '2023-12-14T23:00:00+08:00', 'step_minutes': 10,
            'entry_minutes': 360, 'deadline_minutes': 390,
            'queue_limit_people': 1000, 'budget_yuan': 24000,
            'waiting_comfort_density_people_m2': None,
            'standing_density_limit_people_m2': 2.0,
            'standing_person_minutes_limit': 3000,
            'shared_service_people_per_hour': 2000,
            'bus_fleet_size': 6, 'bus_trip_limit': 20, 'bus_bays': 1,
            'bus_seats': 40, 'bus_legal_capacity': 60, 'bus_standing_area_m2': 10,
            'bus_boarding_minutes': 10, 'bus_turnaround_minutes': 10,
            'bus_prepare_minutes': 60, 'taxi_prepare_minutes': 60,
            'bus_service_end_minutes': 360, 'taxi_service_end_minutes': 360,
            'vehicle_shift_end_minutes': 480,
            'taxi_block_people': 10, 'taxi_block_cost_yuan': 100,
            'taxi_max_blocks_per_step': 8, 'taxi_total_blocks': 200,
            'receiver_open_minutes': 0, 'receiver_close_minutes': 480,
        },
        'directions': [
            {'id': 'A', 'label': '方向甲（合成方向）', 'share': .5, 'initial_queue': 0,
             'waiting_area_m2': 400, 'queue_limit_people': 800,
             'base_people_per_hour': 600, 'bus_ride_minutes': 30, 'taxi_ride_minutes': 20,
             'base_ride_minutes': 20, 'bus_trip_cost_yuan': 420,
             'receiver_people_per_hour': 1500},
            {'id': 'B', 'label': '方向乙（合成方向）', 'share': .3, 'initial_queue': 0,
             'waiting_area_m2': 300, 'queue_limit_people': 600,
             'base_people_per_hour': 360, 'bus_ride_minutes': 40, 'taxi_ride_minutes': 30,
             'base_ride_minutes': 30, 'bus_trip_cost_yuan': 480,
             'receiver_people_per_hour': 1200},
            {'id': 'C', 'label': '方向丙（合成方向）', 'share': .2, 'initial_queue': 0,
             'waiting_area_m2': 200, 'queue_limit_people': 400,
             'base_people_per_hour': 240, 'bus_ride_minutes': 50, 'taxi_ride_minutes': 40,
             'base_ride_minutes': 40, 'bus_trip_cost_yuan': 540,
             'receiver_people_per_hour': 900},
        ],
        'arrival_profiles': [
            {'id': 'uniform', 'label': '均匀进入', 'hourly_people': [1000]*6},
            {'id': 'front', 'label': '前段集中', 'hourly_people': [2000,2000,500,500,500,500]},
            {'id': 'middle', 'label': '中段集中', 'hourly_people': [500,500,2000,2000,500,500]},
            {'id': 'back', 'label': '后段集中', 'hourly_people': [500,500,500,500,2000,2000]},
        ],
    }


if __name__ == '__main__':
    CARD.write_text(json.dumps(make_card(), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(CARD)
