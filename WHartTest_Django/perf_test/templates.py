"""性能测试场景模板库：预置常见压测场景，供一键创建。"""

SCENARIO_TEMPLATES = {
    'login': {
        'name': '登录压测',
        'description': '典型登录接口压测模板，模拟用户登录请求',
        'requests': [
            {
                'name': '用户登录', 'method': 'POST', 'url': '/api/login',
                'headers': {'Content-Type': 'application/json'},
                'params': {}, 'body': {'username': 'test', 'password': '123456'},
                'variables': {}, 'validators': [], 'weight': 1, 'order': 0,
            },
        ],
        'plan': {'users': 50, 'spawn_rate': 5, 'duration': 60, 'think_time': 0.5},
    },
    'list_query': {
        'name': '列表查询压测',
        'description': '分页列表查询接口压测模板',
        'requests': [
            {
                'name': '查询列表', 'method': 'GET', 'url': '/api/list',
                'headers': {}, 'params': {'page': 1, 'size': 20},
                'body': {}, 'variables': {}, 'validators': [], 'weight': 1, 'order': 0,
            },
            {
                'name': '查询详情', 'method': 'GET', 'url': '/api/detail/1',
                'headers': {}, 'params': {},
                'body': {}, 'variables': {}, 'validators': [], 'weight': 1, 'order': 1,
            },
        ],
        'plan': {'users': 100, 'spawn_rate': 10, 'duration': 60, 'think_time': 0.2},
    },
    'order_flow': {
        'name': '下单流程压测',
        'description': '下单业务流程压测模板（下单 + 支付）',
        'requests': [
            {
                'name': '创建订单', 'method': 'POST', 'url': '/api/order',
                'headers': {'Content-Type': 'application/json'},
                'params': {}, 'body': {'product_id': 1, 'quantity': 1},
                'variables': {}, 'validators': [], 'weight': 1, 'order': 0,
            },
            {
                'name': '支付订单', 'method': 'POST', 'url': '/api/pay',
                'headers': {'Content-Type': 'application/json'},
                'params': {}, 'body': {'order_id': 1},
                'variables': {}, 'validators': [], 'weight': 1, 'order': 1,
            },
        ],
        'plan': {'users': 80, 'spawn_rate': 8, 'duration': 120, 'think_time': 1.0},
    },
}


def list_templates():
    return [
        {'key': key, 'name': value['name'], 'description': value['description']}
        for key, value in SCENARIO_TEMPLATES.items()
    ]


def get_template(key):
    return SCENARIO_TEMPLATES.get(key)
