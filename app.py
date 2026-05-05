import dash, os
from dash import ALL, MATCH, dcc, html, Input, Output, callback, dash, callback_context, State
import pandas as pd
import plotly.graph_objects as go
import mysql.connector
from mysql.connector import Error
import urllib.parse
import bcrypt
from flask import session
from dotenv import load_dotenv
import base64
from flask import send_from_directory
import uuid
import json, requests
from datetime import datetime
import qrcode
import io

# Загружаем переменные окружения из .env файла
load_dotenv()

def bring_address(cursor, admin_location):      
    cursor.execute(f"SELECT * FROM admin_location WHERE Admin_Location_ID = {admin_location};")
    location = cursor.fetchone()
    if not location:
        return None
    full_path = []
    current_id = location["Admin_Location_ID"]
    while True:
        ""
        select_parent_query = f"""SELECT * FROM Admin_Location WHERE Admin_Location_ID = {current_id}"""
        cursor.execute(select_parent_query)
        loc_data = cursor.fetchone()
        full_path.append(loc_data['Name'])
                
        if loc_data['Parent_ID'] is None or loc_data['Parent_ID'] == '':
            break
                    
        current_id = loc_data['Parent_ID']
            
    # Инвертируем порядок элементов, чтобы получился правильный адрес сверху-вниз
    full_path.reverse()
    return ', '.join(full_path)

def get_admin_location_options():
    conn = mysql.connector.connect(**DB_CONFIG)
    query = """
        SELECT Admin_Location_ID AS value, Name AS label
        FROM Admin_Location 
        ORDER BY Level, Name;
        """
    df = pd.read_sql(query, conn)
    df['label'] = df['value'].apply(lambda x: bring_address(cursor = conn.cursor(dictionary=True), admin_location = x))
    return df.to_dict('records') if not df.empty else []

# --- НАСТРОЙКИ ПОДКЛЮЧЕНИЯ К БД ---

DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'ssl_disabled': os.getenv('DB_SSL_DISABLED', 'True').lower() == 'true',
    'connection_timeout': int(os.getenv('DB_TIMEOUT', '10')),
}

# --- ИНИЦИАЛИЗАЦИЯ DASH ПРИЛОЖЕНИЯ ---
app = dash.Dash(__name__)
server = app.server

# Секретный ключ для подписи сессий os.environ['SECRET_KEY']
server.secret_key = os.getenv('SECRET_KEY')

server.config['SESSION_COOKIE_SECURE'] = os.getenv('COOKIE_SECURE', 'False').lower() == 'true'
server.config['SESSION_COOKIE_HTTPONLY'] = True
server.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# ---------- Глобальные метаданные о структуре таблиц (загружаются при старте) ----------
def load_table_metadata(table_name):
    """
    Возвращает список словарей с информацией о колонках:
    name, data_type, is_foreign, referenced_table, referenced_column
    """
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor(dictionary=True)

    # Основные типы колонок
    cursor.execute("""
        SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
    """, (DB_CONFIG['database'], table_name))
    columns = {row['COLUMN_NAME']: row for row in cursor.fetchall()}

    # Внешние ключи
    cursor.execute("""
        SELECT COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
        FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND REFERENCED_TABLE_NAME IS NOT NULL
    """, (DB_CONFIG['database'], table_name))
    foreign_keys = {}
    for row in cursor.fetchall():
        foreign_keys[row['COLUMN_NAME']] = {
            'table': row['REFERENCED_TABLE_NAME'],
            'column': row['REFERENCED_COLUMN_NAME']
        }

    result = []
    for col_name, col_info in columns.items():
        fk = foreign_keys.get(col_name)
        result.append({
            'name': col_name,
            'data_type': col_info['DATA_TYPE'],
            'is_foreign': fk is not None,
            'referenced_table': fk['table'] if fk else None,
            'referenced_column': fk['column'] if fk else None
        })

    conn.close()
    return result

# Загружаем метаданные при старте
ATTRACTION_META = load_table_metadata('Attractions')
ROUTE_META = load_table_metadata('Routes')

# Для справочников (все таблицы с простой структурой ID + Name)
DICT_TABLES = {
    'object_types': 'Object_Types',
    'categories': 'Categories',
    'seasons': 'Seasons',
    'difficulties': 'Difficulties',
    'route_types': 'Route_Types',
    'route_themes': 'Route_Themes',
    'object_values': 'Object_Values',
    'object_value_statuses': 'Object_Value_Statuses',
    'technical_conditions': 'Technical_Conditions',
    'object_statuses': 'Object_Statuses',
    'creation_purposes': 'Creation_Purposes',
    'authors': 'Authors',
    'owners': 'Owners',
    'geomorphologies': 'Geomorphologies',
    'recreation_potentials': 'Recreation_Potentials',
    'length_time_metrics': 'Length_Time_Metrics',
    'roles':'Roles'
}

# ---------- Добавьте эти словари после загрузки метаданных ----------
ATTRACTION_FIELD_ALIASES = {
    'Name': 'Название',
    'Object_Type_ID': 'Тип объекта',
    'Category_ID': 'Категория',
    'Description': 'Описание',
    'Admin_Location_ID': 'Административное расположение',
    'Latitude': 'Широта',
    'Longitude': 'Долгота',
    'Accessibility': 'Способы проезда',
    'City_Distance': 'Расстояние от ключевой точки (км)',
    'Key_City_ID': 'Ключевая точка',
    'History': 'Историческая справка',
    'Legends': 'Легенды',
    'Object_Value_ID': 'Значимость объекта',
    'Object_Value_Status_ID': 'Статус значимости',
    'Object_Value_Description': 'Описание значимости',
    'Modernity': 'Благоустройство',
    'Recreation_Potential_ID': 'Рекреационный потенциал',
    'Recreation_Potential_Description': 'Описание рекреационного потенциала',
    'Season_ID': 'Сезон',
    'Time_Recommendation': 'Рекомендуемое время визита',
    'Visitor_Requirements': 'Требования к посетителю',
    'Rules': 'Правила поведения',
    'Guides': 'Гиды',
    'Price': 'Стоимость посещения',
    'Relief': 'Рельеф',
    'Geomorphology_ID': 'Геоморфология',
    'Geologic': 'Геологическое строение',
    'Climate': 'Климат',
    'Hydrology': 'Гидрология',
    'Flora_Fauna': 'Флора и фауна',
    'Ecologic': 'Экологическое состояние',
    'Creation_Date': 'Дата создания',
    'Author_ID': 'Автор',
    'Style_Architecture': 'Архитектурный стиль',
    'Materials_and_Technologies': 'Материалы и технологии',
    'Creation_Purpose_ID': 'Цель создания',
    'Technical_Condition_ID': 'Техническое состояние',
    'Object_Status_ID': 'Статус объекта',
    'Owner_ID': 'Владелец',
    'Restoration_Works': 'Реставрационные работы',
    'TCI': 'Климатический индекс'
}

ROUTE_FIELD_ALIASES = {
    'Name': 'Название маршрута',
    'Route_Type_ID': 'Тип маршрута',
    'Route_Theme_ID': 'Тема маршрута',
    'Difficulty_ID': 'Сложность',
    'Length': 'Протяжённость (км)',
    'Length_Time': 'Продолжительность',
    'Length_Time_Metric_ID': 'Единица измерения времени',
    'Description': 'Описание маршрута',
    'Recommendations': 'Рекомендации по снаряжению',
    'Season_ID': 'Сезон',
    'Organisators_Contacts': 'Контакты организаторов',
    'Admin_Location_ID': 'Административное расположение',
    'Start_Point_Latitude': 'Широта начала маршрута',
    'Start_Point_Longitude': 'Долгота начала маршрута',
    'End_Point_Latitude': 'Широта конца маршрута',
    'End_Point_Longitude': 'Долгота конца маршрута'
}

# Порядок полей в формах (в соответствии с таблицами в БД)
ATTRACTION_ORDER = [
    'Name', 'Object_Type_ID', 'Category_ID', 'Description', 'Admin_Location_ID',
    'Latitude', 'Longitude', 'Accessibility', 'City_Distance', 'Key_City_ID',
    'History', 'Legends', 'Object_Value_ID', 'Object_Value_Status_ID',
    'Object_Value_Description', 'Modernity', 'Recreation_Potential_ID',
    'Recreation_Potential_Description', 'Season_ID', 'Time_Recommendation',
    'Visitor_Requirements', 'Rules', 'Guides', 'Price', 'Relief',
    'Geomorphology_ID', 'Geologic', 'Climate', 'Hydrology', 'Flora_Fauna',
    'Ecologic', 'Creation_Date', 'Author_ID', 'Style_Architecture',
    'Materials_and_Technologies', 'Creation_Purpose_ID',
    'Technical_Condition_ID', 'Object_Status_ID', 'Owner_ID',
    'Restoration_Works', 'TCI'
]

ROUTE_ORDER = [
    'Name', 'Route_Type_ID', 'Route_Theme_ID', 'Difficulty_ID', 'Length',
    'Length_Time', 'Length_Time_Metric_ID', 'Description', 'Recommendations',
    'Season_ID', 'Organisators_Contacts', 'Admin_Location_ID',
    'Start_Point_Latitude', 'Start_Point_Longitude', 'End_Point_Latitude',
    'End_Point_Longitude'
]


# --- ГЕНЕРАЦИЯ ЛЕЙАУТА ---
app.layout = html.Div([
    dcc.Location(id='url', refresh=False), # Основной компонент навигации
    html.Div(id='main-page-layout', style={'display':'block'}, children=
    [
        # Панель аутентификации (динамически обновляется)
        html.Div(id='auth-controls', style={'textAlign': 'right', 'padding': '10px'}),
        
        html.H1("Визуализация туристических маршрутов", style={'textAlign': 'center'}),

     # НОВЫЙ БЛОК: Фильтр по локации
    html.Div([
        html.Label("Выберите административную локацию:"),
        dcc.Dropdown(
            id='location-filter',
            placeholder="Выберите локацию...",
            clearable=False,
            options=[], # Опции загрузятся из БД
            value=1 # По умолчанию ID 1 (Россия)
        ),
    ], style={'width': '50%', 'margin': 'auto', 'padding': '20px'}),
    html.Div([
        html.Label("Фильтр по достопримечательностям:"),
        dcc.Dropdown(
            id='attraction-filter',
            placeholder="Выберите достопримечательности...",
            multi=True,
            clearable=True,
            options=[]
        ),
    ], style={'width': '50%', 'margin': 'auto', 'padding': '10px'}),

    html.Div([
        html.Label("Тип маршрута:"),
        dcc.Dropdown(
            id='route-type-filter',
            placeholder="Любой",
            clearable=True,
            options=[]
        ),
    ], style={'width': '50%', 'margin': 'auto', 'padding': '10px'}),

    html.Div([
        html.Label("Сложность:"),
        dcc.Dropdown(
            id='difficulty-filter',
            placeholder="Любая",
            clearable=True,
            options=[]
        ),
    ], style={'width': '50%', 'margin': 'auto', 'padding': '10px'}),

    html.Div([
        html.Label("Сезон:"),
        dcc.Dropdown(
            id='season-filter',
            placeholder="Любой",
            clearable=True,
            options=[]
        ),
    ], style={'width': '50%', 'margin': 'auto', 'padding': '10px'}),

    html.Div([
        html.Label("Тема маршрута:"),
        dcc.Dropdown(
            id='route-theme-filter',
            placeholder="Любая",
            clearable=True,
            options=[]
        ),
    ], style={'width': '50%', 'margin': 'auto', 'padding': '10px'}),
    
    html.Div([
        html.Label("Выберите маршрут:"),
        dcc.Dropdown(
            id='route-dropdown',
            placeholder="Выберите маршрут...",
            clearable=False,
            value=None,
            options=[]
        ),
    ], style={'width': '50%', 'margin': 'auto', 'padding': '20px'}),
    html.Div([
        # График карты (слева)
        dcc.Graph(id='map-graph', style={'width': '70%', 'display': 'inline-block', 'vertical-align': 'top'}),
    
        # Блок с информацией о маршруте (справа)
        html.Div(id='route-info-container', style={'width': '28%', 'display': 'inline-block', 'padding': '20px', 'box-sizing': 'border-box'}),
    ]),
    # Скрытые элементы для хранения данных и работы с URL
     dcc.Store(id='routes-meta-store'), 
    dcc.Store(id='routes-data-store'), # Здесь хранятся только координаты точек
]),
    # 3. БЛОК СТРАНИЦЫ ДОСТОПРИМЕЧАТЕЛЬНОСТИ (скрыт по умолчанию)
    html.Div(id='attraction-page-layout', style={'display': 'none'}, children=[
        # Кнопка для возврата на главную страницу
        html.Div([
            html.Button("← Назад к маршрутам", id='back-to-main-btn', n_clicks=0, style={'margin-bottom': '20px'}),
            html.A("На главную", href="/", style={'margin-left': '10px'})
        ]),
        # Здесь будет динамически генерироваться контент
        html.Div(id='attraction-content-holder'),
    ]),
    
    # === СТРАНИЦА ЛОГИНА ===
    html.Div(id='login-page-layout', style={'display': 'none'}, children=[
        html.H2("Вход в систему"),
        html.Div([
            dcc.Input(id='login-username', type='text', placeholder='Логин'),
            dcc.Input(id='login-password', type='password', placeholder='Пароль'),
            html.Button('Войти', id='login-button'),
            html.Div(id='login-error-message', style={'color': 'red'})
        ]),
        html.Br(),
        html.A("На главную", href="/")
    ]),

    # === СТРАНИЦА РЕГИСТРАЦИИ ПОЛЬЗОВАТЕЛЯ (ТОЛЬКО АДМИН) ===

    html.Div(id='admin-register-page-layout', style={'display': 'none'}, children=[
        html.H2("Регистрация нового пользователя"),
        html.Div([
            html.Label("Логин:"),
            dcc.Input(id='register-username', type='text', placeholder='Логин'),
            html.Label("Пароль:"),
            dcc.Input(id='register-password', type='password', placeholder='Пароль'),
            html.Label("Роль:"),
            dcc.Dropdown(id='register-role', placeholder="Выберите роль", clearable=False),
            html.Button('Зарегистрировать', id='register-button'),
            html.Div(id='register-message')
        ]),
        html.Br(),
        html.A("На главную", href="/")
    ]),

    #Макет административной панели
    html.Div(id='admin-page-layout', style={'display': 'none'}, children=[
        html.H2("Панель администратора"),
        html.A("На главную", href="/", style={'margin-bottom': '10px', 'display': 'block'}),
        dcc.Tabs(id="admin-tabs", value='tab-attractions', children=[
            dcc.Tab(label='Достопримечательности', value='tab-attractions'),
            dcc.Tab(label='Маршруты', value='tab-routes'),
            dcc.Tab(label='Справочники', value='tab-dicts'),
        ]),
        html.Div(id='admin-content')
    ])
])

# --- КОЛБЭКИ (ЛОГИКА) ---

# 0. Загружаем список локаций для фильтра
@app.callback(
    Output('location-filter', 'options'),
    Input('url', 'pathname')
)
def load_locations(_):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        query = """
        SELECT Admin_Location_ID AS value, Name AS label
        FROM Admin_Location 
        ORDER BY Level, Name;
        """
        df = pd.read_sql(query, conn)
        df['label'] = df['value'].apply(lambda x: bring_address(cursor = conn.cursor(dictionary=True), admin_location = x))
        return df.to_dict('records') if not df.empty else []
    except Error as e:
        print(f"Ошибка при загрузке локаций: {e}")
        return []
    finally:
        if conn.is_connected():
            conn.close()

# 1. Загружаем ГЕО-данные (координаты точек) для всех маршрутов
@app.callback(
    Output('routes-data-store', 'data'),
    Input('url', 'pathname')
)
def load_routes_data(_):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        query = """
        SELECT 
            r.Route_ID,
            r.Name AS Route_Name,
            r.Start_Point_Latitude AS lat,
            r.Start_Point_Longitude AS lon,
            'Старт маршрута' AS Attraction_Name,
            NULL AS Attraction_ID,
            0 AS Stop_Number 
        FROM Routes r

        UNION ALL

        SELECT 
            r.Route_ID,
            r.Name,
            a.Latitude,
            a.Longitude,
            a.Name,
            a.Attraction_ID,
            ra.Number 
        FROM Routes r
        JOIN Routes_Attractions ra ON r.Route_ID = ra.Route_ID
        JOIN Attractions a ON ra.Attraction_ID = a.Attraction_ID

        UNION ALL

        SELECT 
            r.Route_ID,
            r.Name,
            r.End_Point_Latitude,
            r.End_Point_Longitude,
            'Финиш маршрута',
            NULL,
            9999 
        FROM Routes r

        ORDER BY Route_ID, Stop_Number;
        """
        df = pd.read_sql(query, conn)
        return df.to_dict('records') if not df.empty else []
    except Error as e:
        print(f"Ошибка при загрузке координат: {e}")
        return []
    finally:
        if conn.is_connected():
            conn.close()

# 2. Загружаем данные о маршрутах И фильтруем
@app.callback(
    Output('route-dropdown', 'options'),
    Output('routes-meta-store', 'data'),
    Input('location-filter', 'value'),
    Input('attraction-filter', 'value'),
    Input('route-type-filter', 'value'),
    Input('difficulty-filter', 'value'),
    Input('season-filter', 'value'),
    Input('route-theme-filter', 'value')
)
def filter_routes(selected_location_id, selected_attrs, selected_route_type,
                  selected_difficulty, selected_season, selected_theme):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        query = "SELECT Route_ID, Name, Admin_Location_ID, Route_Type_ID, Difficulty_ID, Season_ID, Route_Theme_ID FROM Routes WHERE Deleted = 0"
        df_routes = pd.read_sql(query, conn)
        conn.close()
    except Error as e:
        print(f"Ошибка загрузки маршрутов: {e}")
        return [], []

    if df_routes.empty:
        return [], []

    # 1. Фильтр по локации
    if selected_location_id:
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            query_locations = """
            WITH RECURSIVE loc_tree AS (
                SELECT Admin_Location_ID FROM Admin_Location WHERE Admin_Location_ID = %s
                UNION ALL
                SELECT al.Admin_Location_ID FROM Admin_Location al
                INNER JOIN loc_tree lt ON al.Parent_ID = lt.Admin_Location_ID
            )
            SELECT Admin_Location_ID FROM loc_tree;
            """
            loc_df = pd.read_sql(query_locations, conn, params=(selected_location_id,))
            conn.close()
            if not loc_df.empty:
                valid_ids = loc_df['Admin_Location_ID'].tolist()
                df_routes = df_routes[df_routes['Admin_Location_ID'].isin(valid_ids)]
        except Error as e:
            print(f"Ошибка фильтрации локации: {e}")

    # 2. Фильтр по достопримечательностям (AND – маршрут должен содержать ВСЕ выбранные)
    if selected_attrs and len(selected_attrs) > 0:
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            placeholders = ','.join(['%s'] * len(selected_attrs))
            query_attr = f"""
                SELECT ra.Route_ID
                FROM Routes_Attractions ra
                JOIN Attractions a ON ra.Attraction_ID = a.Attraction_ID
                WHERE a.Attraction_ID IN ({placeholders}) AND a.Deleted = 0
                GROUP BY ra.Route_ID
                HAVING COUNT(DISTINCT ra.Attraction_ID) = %s
            """
            df_attr = pd.read_sql(query_attr, conn, params=selected_attrs + [len(selected_attrs)])
            conn.close()
            if not df_attr.empty:
                route_ids = df_attr['Route_ID'].tolist()
                df_routes = df_routes[df_routes['Route_ID'].isin(route_ids)]
            else:
                return [], []
        except Error as e:
            print(f"Ошибка фильтра достопримечательностей: {e}")

    # 3. Тип маршрута
    if selected_route_type:
        df_routes = df_routes[df_routes['Route_Type_ID'] == selected_route_type]

    # 4. Сложность
    if selected_difficulty:
        df_routes = df_routes[df_routes['Difficulty_ID'] == selected_difficulty]

    # 5. Сезон
    if selected_season:
        df_routes = df_routes[df_routes['Season_ID'] == selected_season]

    # 6. Тема
    if selected_theme:
        df_routes = df_routes[df_routes['Route_Theme_ID'] == selected_theme]

    if df_routes.empty:
        return [], []

    options = [{'label': row['Name'], 'value': row['Route_ID']} for _, row in df_routes.iterrows()]
    return options, df_routes.to_dict('records')


# 3. Читаем ID маршрута из URL и устанавливаем его в Dropdown
@app.callback(
    Output('route-dropdown', 'value'),
    Input('url', 'href'),
    Input('route-dropdown', 'options')
)
def set_dropdown_value_from_url(href, options):
    if not options or not href:
        return dash.no_update

    parsed_url = urllib.parse.urlparse(href)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    
    if 'route_id' in query_params:
        try:
            route_id = int(query_params['route_id'][0])
            
            # Проверяем, существует ли такой маршрут в загруженных данных
            ids = [opt['value'] for opt in options]
            if route_id in ids:
                return route_id
                
        except ValueError:
            pass
    return dash.no_update

# 4. Главная функция: обновляем карту и информацию при выборе маршрута
@app.callback(
    Output('map-graph', 'figure'),
    Output('route-info-container', 'children'),
    Input('route-dropdown', 'value'),
    Input('routes-data-store', 'data'),
    Input('url', 'href')
)
def update_map_and_info(selected_route_id, geo_data, href):
    """Обновляет карту и блок информации при выборе маршрута."""
    
    # Сброс состояния, если маршрут не выбран
    if not geo_data or not selected_route_id:
        empty_fig = {
             "layout": {
                 "xaxis": {"visible": False},
                 "yaxis": {"visible": False},
                 "annotations": [{
                     "text": "Выберите маршрут из списка",
                     "xref": "paper", "yref": "paper",
                     "showarrow": False, "font": {"size": 16}
                 }]
             }
         }
        return empty_fig, html.Div()
    
    # --- ЧАСТЬ 1: ОТРИСОВКА КАРТЫ (используем данные из routes-data-store) ---
    df_points = pd.DataFrame(geo_data)
    route_points_df = df_points[df_points['Route_ID'] == selected_route_id]

    fig = go.Figure()

    # Попытка получить сохранённую дорожную геометрию маршрута
    route_geom = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT route_geometry FROM Routes WHERE Route_ID = %s", (selected_route_id,))
        row = cursor.fetchone()
        if row and row['route_geometry']:
            # Если хранится как строка JSON, десериализуем
            if isinstance(row['route_geometry'], str):
                route_geom = json.loads(row['route_geometry'])
            else:
                route_geom = row['route_geometry']
        conn.close()
    except:
        pass
    
    # Линия маршрута
    if route_geom and 'coordinates' in route_geom:
        coords = route_geom['coordinates']
        lats = [pt[1] for pt in coords]
        lons = [pt[0] for pt in coords]
        fig.add_trace(go.Scattermapbox(
            lat=lats, lon=lons, mode='lines',
            line=dict(color='blue', width=4), name='Маршрут', hoverinfo='skip'
        ))
    else:
        fig.add_trace(go.Scattermapbox(
            lat=route_points_df['lat'],
            lon=route_points_df['lon'],
            mode='lines',
            line=dict(color='blue', width=4),
            name='Маршрут',
            hoverinfo='skip'
        ))

    # Фильтруем только реальные достопримечательности (у них есть Attraction_ID > 0)
    # Старт и Финиш мы исключаем из этого списка, чтобы по ним нельзя было перейти.
    attractions_df = route_points_df[
        (route_points_df['Attraction_Name'] != 'Старт маршрута') & 
        (route_points_df['Attraction_Name'] != 'Финиш маршрута')
    ].copy()

    # Сортируем по порядку в маршруте (Number)
    attractions_df = attractions_df.sort_values('Stop_Number')
    
    customdata = attractions_df[['Attraction_ID', 'Attraction_Name']].copy()
    customdata['Number'] = range(1, len(customdata) + 1)  # порядковые номера
    # Точки (маркеры)
    fig.add_trace(go.Scattermapbox(
        lat=attractions_df['lat'],
        lon=attractions_df['lon'],
        mode='markers',

        text = attractions_df["Attraction_Name"],

        customdata=customdata.values,
        # --- НАСТРОЙКА ПОДСКАЗОК (TOOLTIP) ---
        hovertemplate=(
            "<b>№ %{customdata[2]}</b><br>" +  
            "%{customdata[1]}<br>" +           
            "ID: %{customdata[0]}<br>" +       
            "Широта: %{lat}<br>" +
            "Долгота: %{lon}<br>" +
            "<extra></extra>"
        ),
        
        marker=dict(size=12, color='red'),
        name='Достопримечательности',
        hoverinfo='skip'
    ))

    # --- СЛЕД 3: СТАРТ И ФИНИШ (не кликабельные точки) ---
    # Фильтруем только Старт и Финиш
    start_finish_df = route_points_df[
        (route_points_df['Attraction_Name'] == 'Старт маршрута') | 
        (route_points_df['Attraction_Name'] == 'Финиш маршрута')
    ]

    start_df = route_points_df[
        (route_points_df['Attraction_Name'] == 'Старт маршрута')
    ]

    finish_df = route_points_df[
        (route_points_df['Attraction_Name'] == 'Финиш маршрута')
    ]

    fig.add_trace(go.Scattermapbox(
        lat=start_df['lat'],
        lon=start_df['lon'],
        mode='markers',
        
        # У этих точек НЕТ customdata, поэтому по ним нельзя будет кликнуть для перехода
        
        marker=dict(size=12, color='green'), 
        # Зеленый цвет, чтобы визуально отличить от красных достопримечательностей
        
        hovertemplate="<b>%{text}</b><extra></extra>",
        
        text=start_df['Attraction_Name'],
        name='Точка старта',
        hoverinfo='skip' # Используем свой hovertemplate
    ))

    fig.add_trace(go.Scattermapbox(
        lat=finish_df['lat'],
        lon=finish_df['lon'],
        mode='markers',
        
        # У этих точек НЕТ customdata, поэтому по ним нельзя будет кликнуть для перехода
        
        marker=dict(size=12, color='orange'), 
        # Зеленый цвет, чтобы визуально отличить от красных достопримечательностей
        
        hovertemplate="<b>%{text}</b><extra></extra>",
        
        text=finish_df['Attraction_Name'],
        name='Точка финиша',
        hoverinfo='skip' # Используем свой hovertemplate
    ))
    
    fig.update_layout(
         mapbox_style="open-street-map",
         mapbox_zoom=10,
         mapbox_center_lat=route_points_df['lat'].mean(),
         mapbox_center_lon=route_points_df['lon'].mean(),
         margin={"r":20,"t":40,"l":0,"b":0},
         showlegend=True,
     )
     
    # --- ЧАСТЬ 2: ПОЛУЧЕНИЕ ВСЕЙ ИНФОРМАЦИИ О МАРШРУТЕ (НОВЫЙ ЗАПРОС В БД!) ---
    info_html = html.Div()
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        
        # Запрос выбираем все поля из таблицы Routes для выбранного ID
        query = """
    SELECT 
        r.*,
        al.Name as Admin_Location_Name,
        rt.Name as Route_Type_Name,
        rth.Name as Route_Theme_Name,
        d.Name as Difficulty_Name,
        ltm.Name as Length_Time_Metric_Name,
        s.Name as Season_Name
    FROM Routes r
    LEFT JOIN Admin_Location al ON r.Admin_Location_ID = al.Admin_Location_ID
    LEFT JOIN Route_Types rt ON r.Route_Type_ID = rt.Route_Type_ID
    LEFT JOIN Route_Themes rth ON r.Route_Theme_ID = rth.Route_Theme_ID
    LEFT JOIN Difficulties d ON r.Difficulty_ID = d.Difficulty_ID
    LEFT JOIN Length_Time_Metrics ltm ON r.Length_Time_Metric_ID = ltm.Length_Time_Metric_ID
    LEFT JOIN Seasons s ON r.Season_ID = s.Season_ID
    WHERE r.Route_ID = %s;
    """#"SELECT * FROM Routes WHERE Route_ID = %s;"
        
        info_df = pd.read_sql(query, conn, params=(selected_route_id,), dtype=object)
         
        if not info_df.empty:
            row = info_df.iloc[0]
             
            # Динамически создаем HTML-блок со всеми полями из таблицы
            content = []
            skip_fields = {'Route_ID', 'Start_Point_Latitude', 'Start_Point_Longitude',
                       'End_Point_Latitude', 'End_Point_Longitude', 'route_geometry',
                       'Deleted', 'Creator_User_ID', 'Last_Updated_User_ID',
                       'Route_Type_ID', 'Route_Theme_ID',
                       'Difficulty_ID', 'Length_Time_Metric_ID', 'Season_ID'}
            aliases = {
                'Admin_Location_Name': 'Административное расположение',
                'Route_Type_Name': 'Тип маршрута',
                'Route_Theme_Name': 'Тема маршрута',
                'Difficulty_Name': 'Сложность',
                'Length_Time_Metric_Name': 'Единица измерения времени',
                'Season_Name': 'Сезон',
                'Name':'Название маршрута',
                'Length':'Протяжённость маршрута (км)',
                'Length_Time':'Продолжительность маршрута',
                'Description':'Описание',
                'Recommendations':'Рекоммендации по снаряжению и провианту',
                'Organisators_Contacts':'Контакты организаторов экскурсий'
            }
            for idx, col in enumerate(info_df.columns):
                # Приводим имена к красивому виду и пропускаем технические ID
                if col in aliases:
                    display_name = aliases[col]
                else:
                    display_name = col.replace('_', ' ').title()                                
                #display_name = aliases[col]
                value = row[col]
                if col in skip_fields:#['route_geometry','Start_Point_Latitude','Start_Point_Longitude', 'End_Point_Latitude', 'End_Point_Longitude']:
                    continue

                if col in ['Admin_Location_ID']:
                    display_name = "Административное расположение"
                    value = bring_address(conn.cursor(dictionary=True), value)

                if value is None or (isinstance(value, str) and value.strip() == ''):
                    continue
                
                value_for_display = "" if value is None else str(value).replace('\n','<br>')
                

                content.append(html.P(
                    [html.B(f"{display_name}: "), dcc.Markdown(value_for_display)],
                    key=f"info-row-{idx}"
                ))
             
            info_html = html.Div([
                html.H3(row['Name']),
                html.Hr(),
                *content # Распаковываем список параграфов
            ])
             
            fig.update_layout(title_text=f"Маршрут: {row['Name']}")
        else:
            info_html=html.Div("Маршрут не найден")
             
    except Error as e:
        print(f"Ошибка при получении информации о маршруте: {e}")
        info_html = html.Div("Ошибка загрузки информации о маршруте.")
    finally:
        if conn.is_connected():
            conn.close()
    qr_block = html.Div()
    if selected_route_id and href:
        try:
            parsed = urllib.parse.urlparse(href)
            base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            route_url = f"{base_url}?route_id={selected_route_id}"

            # Генерируем QR-код
            qr = qrcode.QRCode(version=1, box_size=6, border=2)
            qr.add_data(route_url)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

            # Создаём новое изображение с местом для текста
            from PIL import ImageDraw, ImageFont, Image
            width, height = qr_img.size
            # Добавляем снизу 30 пикселей для подписи
            new_height = height + 30
            combined = Image.new("RGB", (width, new_height), "white")
            combined.paste(qr_img, (0, 0))

            # Рисуем текст
            draw = ImageDraw.Draw(combined)
            # Используем стандартный шрифт, т.к. системный может отсутствовать
            try:
                font = ImageFont.truetype("arial.ttf", 12)
            except:
                font = ImageFont.load_default()
            # Получим ширину текста для центрирования
            text = route_url
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_x = (width - text_width) // 2
            draw.text((text_x, height + 5), text, fill="black", font=font)

            # Конвертируем в base64
            buffer = io.BytesIO()
            combined.save(buffer, format="PNG")
            img_str = base64.b64encode(buffer.getvalue()).decode("utf-8")

            qr_block = html.Div([
                html.Img(src=f"data:image/png;base64,{img_str}", style={"width": "160px", "display": "block", "margin": "0 auto"})
            ], style={"textAlign": "center", "marginBottom": "20px"})
        except Exception as e:
            qr_block = html.Div(f"Ошибка QR-кода: {e}")

    # Размещаем QR-код перед остальной информацией
    info_html = html.Div([qr_block, info_html])
    
       
    return fig, info_html

# === ФИЛЬТРЫ ===

@app.callback(
    Output('attraction-filter', 'options'),
    Input('url', 'pathname')
)
def load_attraction_filter(_):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        df = pd.read_sql("SELECT Attraction_ID AS value, Name AS label FROM Attractions WHERE Deleted = 0 ORDER BY Name", conn)
        conn.close()
        return df.to_dict('records')
    except:
        return []

@app.callback(
    Output('route-type-filter', 'options'),
    Input('url', 'pathname')
)
def load_route_type_options(_):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        df = pd.read_sql("SELECT Route_Type_ID AS value, Name AS label FROM Route_Types WHERE Deleted = 0 ORDER BY Name", conn)
        conn.close()
        return df.to_dict('records')
    except:
        return []

@app.callback(
    Output('difficulty-filter', 'options'),
    Input('url', 'pathname')
)
def load_difficulty_options(_):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        df = pd.read_sql("SELECT Difficulty_ID AS value, Name AS label FROM Difficulties WHERE Deleted = 0 ORDER BY Name", conn)
        conn.close()
        return df.to_dict('records')
    except:
        return []

@app.callback(
    Output('season-filter', 'options'),
    Input('url', 'pathname')
)
def load_season_options(_):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        df = pd.read_sql("SELECT Season_ID AS value, Name AS label FROM Seasons WHERE Deleted = 0 ORDER BY Name", conn)
        conn.close()
        return df.to_dict('records')
    except:
        return []

@app.callback(
    Output('route-theme-filter', 'options'),
    Input('url', 'pathname')
)
def load_route_theme_options(_):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        df = pd.read_sql("SELECT Route_Theme_ID AS value, Name AS label FROM Route_Themes WHERE Deleted = 0 ORDER BY Name", conn)
        conn.close()
        return df.to_dict('records')
    except:
        return []



# === КОЛБЭК АУТЕНТИФИКАЦИИ ===
# Обновление ссылок в панели аутентификации

@app.callback(
    Output('auth-controls', 'children'),
    Input('url', 'pathname')
)
def update_auth_controls(pathname):
    children = []
    if 'user_id' in session:
        children.append(html.Span(f"Привет, {session['login']}! ", style={'margin-right': '10px'}))
        children.append(html.A("Выйти", href="/logout"))
        if session.get('role') == 'admin':
            children.append(html.Span(" | "))
            children.append(html.A("Панель администратора", href="/admin"))
            children.append(html.Span(" | "))
            children.append(html.A("Создать пользователя", href="/admin/register"))
    else:
        children.append(html.A("Войти", href="/login"))
    return children

# Обработка входа
@app.callback(
    Output('login-error-message', 'children'),
    Output('url', 'pathname', allow_duplicate=True),
    Input('login-button', 'n_clicks'),
    State('login-username', 'value'),
    State('login-password', 'value'),
    prevent_initial_call=True
)
def handle_login(n_clicks, username, password):
    if not n_clicks or not username or not password:
        return "", dash.no_update
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT User_ID, Login, Password, Role_ID FROM Users WHERE Login = %s", (username,))
        user = cursor.fetchone()
        if user and bcrypt.checkpw(password.encode('utf-8'), user['Password'].encode('utf-8')):
            session['user_id'] = user['User_ID']
            session['login'] = user['Login']
            cursor.execute("SELECT Name FROM Roles WHERE Role_ID = %s", (user['Role_ID'],))
            role_row = cursor.fetchone()
            session['role'] = role_row['Name'].lower() if role_row else 'user'
            return "", "/"  # редирект на главную
        else:
            return "Неверный логин или пароль.", dash.no_update
    except Error as e:
        return f"Ошибка БД: {e}", dash.no_update
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

# Загрузка списка ролей для формы регистрации
@app.callback(
    Output('register-role', 'options'),
    Input('url', 'pathname')
)
def load_roles(pathname):
    if pathname == '/admin/register':
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            query = "SELECT Role_ID AS value, Name AS label FROM Roles"
            df = pd.read_sql(query, conn)
            return df.to_dict('records') if not df.empty else []
        except Error as e:
            return []
        finally:
            if conn.is_connected():
                conn.close()
    return []

# Регистрация нового пользователя (только для админа)
@app.callback(
    Output('register-message', 'children'),
    Output('url', 'pathname', allow_duplicate=True),
    Input('register-button', 'n_clicks'),
    State('register-username', 'value'),
    State('register-password', 'value'),
    State('register-role', 'value'),
    prevent_initial_call=True
)
def register_user(n_clicks, username, password, role_id):
    if not n_clicks or not username or not password or not role_id:
        return "", dash.no_update
    if session.get('role') != 'admin':
        return "У вас нет прав для регистрации пользователей.", dash.no_update
    # Хэшируем пароль
    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO Users (Login, Password, Role_ID) VALUES (%s, %s, %s)", (username, hashed_pw, role_id))
        conn.commit()
        return f"Пользователь '{username}' успешно зарегистрирован.", "/admin/register"
    except Error as e:
        return f"Ошибка: {e}", dash.no_update
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()


# ---------- АДМИНИСТРАТИВНАЯ ПАНЕЛЬ ----------
# Вкладки внутри админки
@app.callback(
    Output('admin-content', 'children'),
    Input('admin-tabs', 'value')
)


# === УПРАВЛЕНИЕ СТРАНИЦАМИ (ОСНОВНОЙ КОЛБЭК) ===
def render_admin_tab(tab):
    if tab == 'tab-attractions':
        return html.Div([
            dcc.Store(id='edit-attraction-id', data=None),
            html.H3("Список достопримечательностей"),
            dcc.Dropdown(id='attraction-select', placeholder='Выберите достопримечательность'),
            html.Button('Новая', id='new-attraction-btn', n_clicks=0),
            html.Br(),
            html.Div(id='attraction-edit-form')
        ])
    elif tab == 'tab-routes':
        return html.Div([
            dcc.Store(id='edit-route-id', data=None),
            dcc.Store(id='osrm-variants-store', data=[]),
            dcc.Store(id='selected-attrs-store', data=[]),  # хранит [{"id": 1, "name": "..."}, ...]
            html.H3("Список маршрутов"),
            dcc.Dropdown(id='route-admin-select', placeholder='Выберите маршрут'),
            html.Button('Новый', id='new-route-btn', n_clicks=0),
            html.Br(),
            html.Div(id='route-edit-form')
        ])
    elif tab == 'tab-dicts':
        return html.Div([
            html.H3("Управление справочниками"),
            dcc.Dropdown(id='dict-type-select', options=[
                {'label': 'Типы объектов', 'value': 'Object_Types'},
                {'label': 'Категории', 'value': 'Categories'},
                {'label': 'Сезоны', 'value': 'Seasons'},
                {'label': 'Сложности', 'value': 'Difficulties'},
                {'label': 'Типы маршрутов', 'value': 'Route_Types'},
                {'label': 'Темы маршрутов', 'value': 'Route_Themes'},
                {'label': 'Ценность объектов', 'value': 'Object_Values'},
                {'label': 'Статусы ценности', 'value': 'Object_Value_Statuses'},
                {'label': 'Технические состояния', 'value': 'Technical_Conditions'},
                {'label': 'Статусы объектов', 'value': 'Object_Statuses'},
                {'label': 'Цели создания', 'value': 'Creation_Purposes'},
                {'label': 'Авторы', 'value': 'Authors'},
                {'label': 'Владельцы', 'value': 'Owners'},
                {'label': 'Геоморфологии', 'value': 'Geomorphologies'},
                {'label': 'Рекреационный потенциал', 'value': 'Recreation_Potentials'},
                {'label': 'Единицы измерения', 'value': 'Length_Time_Metrics'},
                {'label':'Роли пользователей', 'value':'Roles'}
            ], value='Object_Types'),
            html.Button('Добавить запись', id='dict-add-btn'),
            html.Div(id='dict-list-container'),
            html.Div(id='dict-edit-form')
        ])
    return "Выберите вкладку"

# ================== РЕДАКТИРОВАНИЕ ДОСТОПРИМЕЧАТЕЛЬНОСТЕЙ ==================
# Заполнение выпадающего списка
@app.callback(
    Output('attraction-select', 'options'),
    Input('attraction-select', 'search_value'),
)
def update_attraction_list(search):
    conn = mysql.connector.connect(**DB_CONFIG)
    query = "SELECT Attraction_ID AS value, Name AS label FROM Attractions WHERE Deleted = 0"
    df = pd.read_sql(query, conn)
    conn.close()
    return df.to_dict('records')

def generate_attraction_form(attr_id):
    data = {}
    if attr_id:
        conn = mysql.connector.connect(**DB_CONFIG)
        query = "SELECT * FROM Attractions WHERE Attraction_ID = %s"
        df = pd.read_sql(query, conn, params=(attr_id,))
        if not df.empty:
            data = df.iloc[0].to_dict()
        conn.close()

    fields = []
    skip_fields = {'Attraction_ID', 'Deleted', 'Last_Updated', 'Created',
                   'Creator_User_ID', 'Last_Updated_User_ID'}
    meta_dict = {m['name']: m for m in ATTRACTION_META}

    for col_name in ATTRACTION_ORDER:
        if col_name in skip_fields:
            continue
        col_meta = meta_dict.get(col_name)
        if not col_meta:
            continue
        label_name = ATTRACTION_FIELD_ALIASES.get(col_name, col_name)
        value = data.get(col_name, None)
        if isinstance(value, datetime):
            value = value.strftime('%Y-%m-%dT%H:%M')
        elif value is None:
            value = ''

        options = []
        if col_meta['is_foreign']:
            ref_table = col_meta['referenced_table']
            ref_col = col_meta['referenced_column']
            try:
                if ref_table == 'admin_location':
                    options = get_admin_location_options()
                else:
                    conn_temp = mysql.connector.connect(**DB_CONFIG)
                    df_opts = pd.read_sql(f"SELECT {ref_col} AS value, Name AS label FROM {ref_table} WHERE Deleted = 0", conn_temp)
                    conn_temp.close()
                    options = df_opts.to_dict('records')
            except Exception as e:
                print(f"Ошибка загрузки опций для {col_name}: {e}")

        if col_meta['is_foreign']:
            field = html.Div([
                html.Label(label_name),
                dcc.Dropdown(
                    id={'type': 'attr-field', 'name': col_name},
                    options=options,
                    value=value if value != '' else None,
                    placeholder=f"Выберите {label_name.lower()}"
                )
            ])
        else:
            dtype = col_meta['data_type'].lower()
            if dtype in ('int', 'tinyint', 'smallint', 'mediumint', 'bigint', 'decimal', 'float', 'double'):
                field = html.Div([
                    html.Label(label_name),
                    dcc.Input(id={'type': 'attr-field', 'name': col_name}, type='number', value=value,
                              placeholder=f"Введите {label_name.lower()}")
                ])
            elif dtype in ('datetime', 'timestamp'):
                field = html.Div([
                    html.Label(label_name),
                    dcc.Input(id={'type': 'attr-field', 'name': col_name}, type='datetime-local', value=value,
                              placeholder=f"Выберите {label_name.lower()}")
                ])
            else:
                # Все текстовые поля – Textarea (многострочный ввод)
                field = html.Div([
                    html.Label(label_name),
                    dcc.Textarea(
                        id={'type': 'attr-field', 'name': col_name},
                        value=value,
                        placeholder=f"Введите {label_name.lower()}",
                        style={'width': '100%', 'height': 100}
                    )
                ])
        fields.append(field)

    fields.append(html.Div([
        html.Label("Медиа (фото/видео)"),
        dcc.Upload(
            id='upload-media',
            children=html.Div(['Перетащите или ', html.A('выберите')]),
            multiple=True,
            style={'border': '1px dashed', 'padding': '10px'}
        )
    ]))
    fields.append(html.Button('Сохранить', id='save-attraction-btn'))
    fields.append(html.Div(id='attraction-save-status'))
    return html.Div(fields)

# Загрузка данных в форму
@app.callback(
    Output('attraction-edit-form', 'children'),
    Output('edit-attraction-id', 'data'),
    Input('attraction-select', 'value'),
    Input('new-attraction-btn', 'n_clicks'),
)
def load_attraction_form(attraction_id, new_clicks):
    ctx = callback_context
    triggered = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else ''
    if triggered == 'new-attraction-btn' and new_clicks > 0:
        return generate_attraction_form(None), None
    if attraction_id:
        return generate_attraction_form(attraction_id), attraction_id
    return html.Div(), None

@app.callback(
    Output('attraction-save-status', 'children'),
    Input('save-attraction-btn', 'n_clicks'),
    State('edit-attraction-id', 'data'),
    State({'type': 'attr-field', 'name': ALL}, 'value'),
    State({'type': 'attr-field', 'name': ALL}, 'id'),
    prevent_initial_call=True
)
def save_attraction(n_clicks, attr_id, values, ids):
    if not n_clicks:
        return ""
    # Собираем словарь значений, игнорируя None (незаполненные Dropdown)
    data = {}
    for val, id_dict in zip(values, ids):
        col_name = id_dict['name']
        # Находим метаданные колонки для преобразования типов
        col_meta = next((m for m in ATTRACTION_META if m['name'] == col_name), None)
        if val is None or val == '':
            if col_meta and col_meta['is_foreign']:
                # Для внешнего ключа None означает NULL
                data[col_name] = None
            else:
                continue  # пропускаем пустые необязательные поля
        else:
            # Преобразование типа
            if col_meta:
                dtype = col_meta['data_type'].lower()
                if dtype in ('int', 'tinyint', 'smallint', 'mediumint', 'bigint'):
                    data[col_name] = int(val)
                elif dtype in ('decimal', 'float', 'double'):
                    data[col_name] = float(val)
                elif dtype in ('datetime', 'timestamp'):
                    try:
                        data[col_name] = datetime.strptime(val, '%Y-%m-%dT%H:%M')
                    except:
                        data[col_name] = val  # оставляем как есть
                else:
                    data[col_name] = str(val)
            else:
                data[col_name] = val
    user_id = session.get('user_id', None)
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    try:
        if attr_id:
            data['Last_Updated_User_ID'] = user_id
            set_clause = ", ".join([f"{k} = %s" for k in data.keys()])
            cursor.execute(f"UPDATE Attractions SET {set_clause} WHERE Attraction_ID = %s",
                           list(data.values()) + [attr_id])
        else:
            data['Creator_User_ID'] = user_id
            data['Last_Updated_User_ID'] = user_id
            columns = ", ".join(data.keys())
            placeholders = ", ".join(["%s"] * len(data))
            cursor.execute(f"INSERT INTO Attractions ({columns}) VALUES ({placeholders})", list(data.values()))
            attr_id = cursor.lastrowid
        conn.commit()
        return f"Сохранено (ID: {attr_id})"
    except Error as e:
        return f"Ошибка сохранения: {e}"
    finally:
        conn.close()

# Загрузка медиа (без изменений)
@app.callback(
    Output('upload-media', 'children', allow_duplicate=True),
    Input('upload-media', 'contents'),
    State('upload-media', 'filename'),
    State('edit-attraction-id', 'data'),
    prevent_initial_call=True
)
def handle_media_upload(contents_list, names_list, attr_id):
    if not contents_list or not attr_id:
        return "Нет ID достопримечательности"
    saved = []
    for content, name in zip(contents_list, names_list):
        content_type, content_string = content.split(',')
        decoded = base64.b64decode(content_string)
        ext = os.path.splitext(name)[1]
        filename = f"{attr_id}_{uuid.uuid4().hex}{ext}"
        filepath = os.path.join('assets', filename)
        with open(filepath, 'wb') as f:
            f.write(decoded)
        video_exts = ['.mp4', '.webm', '.avi', '.mov']
        media_type = 'video' if ext.lower() in video_exts else 'photo'
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO Media (Attraction_ID, Type, File_Path) VALUES (%s, %s, %s)",
                           (attr_id, media_type, filename))
            conn.commit()
            conn.close()
            saved.append(name)
        except Error as e:
            print(f"Ошибка сохранения медиа: {e}")
    return f"Загружено: {', '.join(saved)}"


# ================== РЕДАКТИРОВАНИЕ МАРШРУТОВ ==================
@app.callback(
    Output('route-admin-select', 'options'),
    Input('route-admin-select', 'search_value')
)
def update_route_list(search):
    conn = mysql.connector.connect(**DB_CONFIG)
    df = pd.read_sql("SELECT Route_ID AS value, Name AS label FROM Routes", conn)
    conn.close()
    return df.to_dict('records')

def generate_route_form(route_id):
    data = {}
    if route_id:
        conn = mysql.connector.connect(**DB_CONFIG)
        df = pd.read_sql("SELECT * FROM Routes WHERE Route_ID = %s", conn, params=(route_id,))
        if not df.empty:
            data = df.iloc[0].to_dict()
        conn.close()

    fields = []
    skip_fields = {'Route_ID', 'Deleted', 'Creator_User_ID', 'Last_Updated_User_ID',
                   'route_geometry', 'Last_Updated', 'Created'}
    meta_dict = {m['name']: m for m in ROUTE_META}

    for col_name in ROUTE_ORDER:
        if col_name in skip_fields:
            continue
        col_meta = meta_dict.get(col_name)
        if not col_meta:
            continue
        label_name = ROUTE_FIELD_ALIASES.get(col_name, col_name)
        value = data.get(col_name, None)
        if isinstance(value, datetime):
            value = value.strftime('%Y-%m-%dT%H:%M')
        elif value is None:
            value = ''

        options = []
        if col_meta['is_foreign']:
            ref_table = col_meta['referenced_table']
            ref_col = col_meta['referenced_column']
            try:
                if ref_table == 'admin_location':
                    options = get_admin_location_options()
                else:
                    conn_temp = mysql.connector.connect(**DB_CONFIG)
                    df_opts = pd.read_sql(f"SELECT {ref_col} AS value, Name AS label FROM {ref_table} WHERE Deleted = 0", conn_temp)
                    conn_temp.close()
                    options = df_opts.to_dict('records')
            except Exception as e:
                print(f"Ошибка загрузки опций для {col_name}: {e}")

        if col_meta['is_foreign']:
            field = html.Div([
                html.Label(label_name),
                dcc.Dropdown(
                    id={'type': 'route-field', 'name': col_name},
                    options=options,
                    value=value if value != '' else None,
                    placeholder=f"Выберите {label_name.lower()}"
                )
            ])
        else:
            dtype = col_meta['data_type'].lower()
            if dtype in ('int', 'tinyint', 'smallint', 'mediumint', 'bigint', 'decimal', 'float', 'double'):
                field = html.Div([
                    html.Label(label_name),
                    dcc.Input(id={'type': 'route-field', 'name': col_name}, type='number', value=value,
                              placeholder=f"Введите {label_name.lower()}")
                ])
            elif dtype in ('datetime', 'timestamp'):
                field = html.Div([
                    html.Label(label_name),
                    dcc.Input(id={'type': 'route-field', 'name': col_name}, type='datetime-local', value=value,
                              placeholder=f"Выберите {label_name.lower()}")
                ])
            else:
                field = html.Div([
                    html.Label(label_name),
                    dcc.Textarea(
                        id={'type': 'route-field', 'name': col_name},
                        value=value,
                        placeholder=f"Введите {label_name.lower()}",
                        style={'width': '100%', 'height': 100}
                    )
                ])
        fields.append(field)

    # --- БЛОК ДОСТОПРИМЕЧАТЕЛЬНОСТЕЙ (восстановлен полностью) ---
    fields.append(html.Hr())
    fields.append(html.H4("Достопримечательности маршрута"))
    fields.append(html.Div([
        dcc.Dropdown(id='route-attr-add-dropdown', placeholder='Выберите существующую'),
        html.Button('Добавить выбранную', id='add-attr-btn', n_clicks=0),
        html.Button('Создать новую', id='new-attr-btn', n_clicks=0),
    ]))
    fields.append(html.Div(id='new-attr-modal', style={'display': 'none'}, children=[
        html.Label("Название"),
        dcc.Input(id='new-attr-name', type='text', placeholder='Введите название'),
        html.Label("Широта"),
        dcc.Input(id='new-attr-lat', type='number', placeholder='Широта'),
        html.Label("Долгота"),
        dcc.Input(id='new-attr-lon', type='number', placeholder='Долгота'),
        html.Button('Сохранить', id='save-new-attr-btn'),
        html.Button('Отмена', id='cancel-new-attr-btn'),
    ]))
    fields.append(html.Div(id='selected-attrs-list'))

    fields.append(html.Hr())
    fields.append(html.Button("Построить варианты маршрута", id='build-osrm-btn', n_clicks=0))
    fields.append(dcc.Graph(id='osrm-options-map', style={'height': '400px'}))
    fields.append(dcc.RadioItems(id='select-osrm-variant', options=[], value=None))
    fields.append(html.Button("Сохранить маршрут", id='save-route-btn'))
    fields.append(html.Div(id='route-save-status'))

    return html.Div(fields)


@app.callback(
    Output('route-edit-form', 'children'),
    Output('edit-route-id', 'data'),
    Output('selected-attrs-store', 'data'),
    Input('route-admin-select', 'value'),
    Input('new-route-btn', 'n_clicks'),
)
def load_route_form(route_id, new_clicks):
    ctx = callback_context
    triggered = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else ''
    if triggered == 'new-route-btn' and new_clicks > 0:
        return generate_route_form(None), None, []
    if route_id:
        # Загружаем существующие достопримечательности в порядке Number
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""SELECT a.Attraction_ID, a.Name
            FROM Routes_Attractions ra JOIN Attractions a ON ra.Attraction_ID = a.Attraction_ID
            WHERE ra.Route_ID = %s ORDER BY ra.Number""", (route_id,))
        selected = [{'id': row['Attraction_ID'], 'name': row['Name']} for row in cursor.fetchall()]
        conn.close()
        return generate_route_form(route_id), route_id, selected
    return html.Div(), None, []

# Загрузка опций для выпадающего списка достопримечательностей
@app.callback(
    Output('route-attr-add-dropdown', 'options'),
    Input('route-attr-add-dropdown', 'search_value')
)
def load_attr_options(search):
    conn = mysql.connector.connect(**DB_CONFIG)
    df = pd.read_sql("SELECT Attraction_ID AS value, Name AS label FROM Attractions WHERE Deleted = 0", conn)
    conn.close()
    return df.to_dict('records')

# Добавление существующей достопримечательности в список
@app.callback(
    Output('selected-attrs-store', 'data', allow_duplicate=True),
    Input('add-attr-btn', 'n_clicks'),
    State('route-attr-add-dropdown', 'value'),
    State('route-attr-add-dropdown', 'options'),
    State('selected-attrs-store', 'data'),
    prevent_initial_call=True
)
def add_attr_to_list(n_clicks, value, options, current_list):
    if not n_clicks or not value:
        return dash.no_update
    # Проверяем, нет ли уже такого ID
    if any(item['id'] == value for item in current_list):
        return dash.no_update
    # Находим название по опциям
    name = next((opt['label'] for opt in options if opt['value'] == value), str(value))
    current_list.append({'id': value, 'name': name})
    return current_list

# Управление модальным окном создания новой достопримечательности
@app.callback(
    Output('new-attr-modal', 'style'),
    Input('new-attr-btn', 'n_clicks'),
    Input('cancel-new-attr-btn', 'n_clicks'),
    State('new-attr-modal', 'style'),
    prevent_initial_call=True
)
def toggle_modal(new_clicks, cancel_clicks, current_style):
    ctx = callback_context
    if not ctx.triggered:
        return dash.no_update
    trig = ctx.triggered[0]['prop_id'].split('.')[0]
    if trig == 'new-attr-btn':
        return {'display': 'block'}
    return {'display': 'none'}

# Сохранение новой достопримечательности и добавление её в список
@app.callback(
    Output('selected-attrs-store', 'data', allow_duplicate=True),
    Output('new-attr-modal', 'style', allow_duplicate=True),
    Input('save-new-attr-btn', 'n_clicks'),
    State('new-attr-name', 'value'),
    State('new-attr-lat', 'value'),
    State('new-attr-lon', 'value'),
    State('selected-attrs-store', 'data'),
    prevent_initial_call=True
)
def save_new_attr(n_clicks, name, lat, lon, current_list):
    if not n_clicks or not name or lat is None or lon is None:
        return dash.no_update, dash.no_update
    user_id=session.get('user_id', None)
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO Attractions (Name, Latitude, Longitude, Creator_User_ID, Last_Updated_User_ID) VALUES (%s, %s, %s, %s, %s)", (name, lat, lon, user_id, user_id))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    current_list.append({'id': new_id, 'name': name})
    return current_list, {'display': 'none'}

# Отображение списка выбранных достопримечательностей с кнопками управления
@app.callback(
    Output('selected-attrs-list', 'children'),
    Input('selected-attrs-store', 'data')
)
def render_selected_attrs(data):
    if not data:
        return html.P("Нет добавленных достопримечательностей")
    items = []
    for i, item in enumerate(data):
        items.append(html.Div([
            html.Span(f"{i+1}. {item['name']} (ID: {item['id']})"),
            html.Button('↑', id={'type': 'move-attr-up', 'index': i}, disabled=i==0),
            html.Button('↓', id={'type': 'move-attr-down', 'index': i}, disabled=i==len(data)-1),
            html.Button('Удалить', id={'type': 'remove-attr', 'index': i})
        ], style={'margin': '5px'}))
    return html.Div(items)

# Перемещение элементов вверх/вниз и удаление
@app.callback(
    Output('selected-attrs-store', 'data', allow_duplicate=True),
    Input({'type': 'move-attr-up', 'index': ALL}, 'n_clicks'),
    Input({'type': 'move-attr-down', 'index': ALL}, 'n_clicks'),
    Input({'type': 'remove-attr', 'index': ALL}, 'n_clicks'),
    State('selected-attrs-store', 'data'),
    prevent_initial_call=True
)
def modify_attr_list(up_clicks, down_clicks, remove_clicks, data):
    ctx = callback_context
    if not ctx.triggered:
        return dash.no_update
    triggered = ctx.triggered[0]
    prop_id = triggered['prop_id']
    idx = json.loads(prop_id.split('.')[0])['index']
    n_clicks = triggered['value']
    if not n_clicks:
        return dash.no_update

    if 'move-attr-up' in prop_id:
        if idx > 0:
            data[idx], data[idx-1] = data[idx-1], data[idx]
    elif 'move-attr-down' in prop_id:
        if idx < len(data) - 1:
            data[idx], data[idx+1] = data[idx+1], data[idx]
    elif 'remove-attr' in prop_id:
        del data[idx]
    return data

# Построение вариантов маршрута через OSRM (использует текущий список selected-attrs-store для порядка)
@app.callback(
    Output('osrm-options-map', 'figure'),
    Output('osrm-variants-store', 'data'),
    Output('select-osrm-variant', 'options'),
    Output('select-osrm-variant', 'value'),
    Input('build-osrm-btn', 'n_clicks'),
    State({'type': 'route-field', 'name': 'Start_Point_Latitude'}, 'value'),
    State({'type': 'route-field', 'name': 'Start_Point_Longitude'}, 'value'),
    State({'type': 'route-field', 'name': 'End_Point_Latitude'}, 'value'),
    State({'type': 'route-field', 'name': 'End_Point_Longitude'}, 'value'),
    State('selected-attrs-store', 'data'),
    prevent_initial_call=True
)
def build_osrm_variants(n_clicks, start_lat, start_lon, end_lat, end_lon, selected_attrs):
    if not n_clicks or None in [start_lat, start_lon, end_lat, end_lon]:
        return dash.no_update, dash.no_update, [], dash.no_update

    # ---- 1. Сбор точек в порядке: старт → достопримечательности → финиш ----
    points = [(start_lon, start_lat)]
    attr_names = []
    if selected_attrs:
        ids = [item['id'] for item in selected_attrs]
        conn = mysql.connector.connect(**DB_CONFIG)
        placeholders = ','.join(['%s'] * len(ids))
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            f"SELECT Attraction_ID, Longitude, Latitude, Name FROM Attractions WHERE Attraction_ID IN ({placeholders})",
            ids
        )
        rows = cursor.fetchall()
        conn.close()
        attr_dict = {row['Attraction_ID']: row for row in rows}
        for item in selected_attrs:
            row = attr_dict.get(item['id'])
            if row:
                points.append((float(row['Longitude']), float(row['Latitude'])))
                attr_names.append(row['Name'])
            else:
                points.append((0, 0))
                attr_names.append(item.get('name', '?'))
    points.append((end_lon, end_lat))

    # ---- 2. Запрос к GraphHopper для двух профилей ----
    api_key = os.getenv('GRAPHHOPPER_API_KEY')
    if not api_key:
        fig = go.Figure()
        fig.add_annotation(text="Ошибка: не задан GRAPHHOPPER_API_KEY", showarrow=False)
        return fig, [], [], dash.no_update

    # Преобразуем точки в параметр `point`
    point_params = "&point=".join([f"{lat},{lon}" for lon, lat in points])
    base_url = "https://graphhopper.com/api/1/route"

    all_routes = []          # список словарей { 'geometry': GeoJSON LineString, 'label': str }
    variants_geom = []       # для сохранения в osrm-variants-store
    options = []             # для RadioItems

    for profile, profile_label in [("car", "🚗 Авто"), ("foot", "🚶 Пешком")]:
        url = (f"{base_url}?point={point_params}&vehicle={profile}"
               f"&locale=ru&key={api_key}"
               f"&alternative_route.max_paths=4"   # до 2 альтернатив на профиль
               f"&instructions=false&points_encoded=false")
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if 'paths' not in data:
                print(f"GraphHopper ({profile}): {data.get('message', 'нет маршрутов')}")
                continue
            paths = data['paths']
            for i, path in enumerate(paths, start=1):
                coords = path['points']['coordinates']   # [[lng, lat], ...]
                geom = {"type": "LineString", "coordinates": coords}
                label = f"{profile_label}, вариант {i}"
                all_routes.append({'geometry': geom, 'label': label})
                variants_geom.append(json.dumps(geom))
                options.append({'label': label, 'value': len(options)})
        except Exception as e:
            print(f"Ошибка запроса к GraphHopper ({profile}): {e}")
            continue

    if not all_routes:
        fig = go.Figure()
        fig.add_annotation(text="Не удалось построить ни одного маршрута", showarrow=False)
        return fig, [], [], dash.no_update

    # ---- 3. Отрисовка карты ----
    fig = go.Figure()
    colors = ['blue', 'green', 'purple', 'orange', 'cyan', 'magenta']
    for idx, route in enumerate(all_routes):
        geom = route['geometry']
        lons, lats = zip(*geom['coordinates'])
        fig.add_trace(go.Scattermapbox(
            lat=lats, lon=lons, mode='lines',
            line=dict(color=colors[idx % len(colors)], width=4),
            name=route['label'],
            hoverinfo='skip'
        ))

    # Маркеры точек (старт, финиш, достопримечательности с номерами)
    labels = ['Старт']
    if attr_names:
        for idx, name in enumerate(attr_names, start=1):
            labels.append(f'{idx}. {name}')
    labels.append('Финиш')

    for i, (lon, lat) in enumerate(points):
        color = 'green' if i == 0 else 'orange' if i == len(points)-1 else 'red'
        size = 12 if i in (0, len(points)-1) else 10
        fig.add_trace(go.Scattermapbox(
            lat=[lat], lon=[lon],
            mode='markers+text',
            text=[labels[i]],
            textposition='top center',
            textfont=dict(size=10, color='black'),
            marker=dict(size=size, color=color),
            hovertemplate=f"<b>{labels[i]}</b><br>Широта: %{{lat}}<br>Долгота: %{{lon}}<extra></extra>",
            showlegend=False
        ))

    fig.update_layout(
        mapbox_style="open-street-map",
        mapbox_zoom=10,
        mapbox_center_lat=sum(p[1] for p in points)/len(points),
        mapbox_center_lon=sum(p[0] for p in points)/len(points),
        margin={"r":0,"t":0,"l":0,"b":0},
        legend=dict(
            y=-0.1,
            yanchor='top',
            orientation='h'
        )
    )

    return fig, variants_geom, options, 0   # первый вариант выбран по умолчанию

# Сохранение маршрута (включая геометрию и связь с достопримечательностями)
@app.callback(
    Output('route-save-status', 'children'),
    Input('save-route-btn', 'n_clicks'),
    State('edit-route-id', 'data'),
    State({'type': 'route-field', 'name': ALL}, 'value'),
    State({'type': 'route-field', 'name': ALL}, 'id'),
    State('select-osrm-variant', 'value'),
    State('osrm-variants-store', 'data'),
    State('selected-attrs-store', 'data'),
    prevent_initial_call=True
)
def save_route(n_clicks, route_id, values, ids, variant_idx, variants, selected_attrs):
    if not n_clicks:
        return ""
    data = {}
    # Создаём словарь метаданных для быстрого поиска (исправление ошибки)
    meta_dict = {m['name']: m for m in ROUTE_META}
    for val, id_dict in zip(values, ids):
        col_name = id_dict['name']
        col_meta = meta_dict.get(col_name)  # <-- теперь корректно
        if val is None or val == '':
            if col_meta and col_meta['is_foreign']:
                data[col_name] = None
            continue
        if col_meta:
            dtype = col_meta['data_type'].lower()
            if dtype in ('int', 'tinyint', 'smallint', 'mediumint', 'bigint'):
                data[col_name] = int(val)
            elif dtype in ('decimal', 'float', 'double'):
                data[col_name] = float(val)
            elif dtype in ('datetime', 'timestamp'):
                try:
                    data[col_name] = datetime.strptime(val, '%Y-%m-%dT%H:%M')
                except:
                    data[col_name] = val
            else:
                data[col_name] = str(val)
        else:
            data[col_name] = val

    # Геометрия
    route_geom = None
    if variants and variant_idx is not None and isinstance(variant_idx, int):
        route_geom = variants[variant_idx]

    user_id = session.get('user_id', None)
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    try:
        if route_id:
            data['Last_Updated_User_ID'] = user_id
            data['Last_Updated'] = datetime.now()
            if route_geom:
                data['route_geometry'] = route_geom
            set_clause = ", ".join([f"{k} = %s" for k in data.keys()])
            cursor.execute(f"UPDATE Routes SET {set_clause} WHERE Route_ID = %s",
                           list(data.values()) + [route_id])
        else:
            data['Creator_User_ID'] = user_id
            data['Last_Updated_User_ID'] = user_id
            data['Created'] = datetime.now()
            data['Last_Updated'] = datetime.now()
            if route_geom:
                data['route_geometry'] = route_geom
            columns = ", ".join(data.keys())
            placeholders = ", ".join(["%s"] * len(data))
            cursor.execute(f"INSERT INTO Routes ({columns}) VALUES ({placeholders})", list(data.values()))
            route_id = cursor.lastrowid

        # Обновляем связи с достопримечательностями
        cursor.execute("DELETE FROM Routes_Attractions WHERE Route_ID = %s", (route_id,))
        for i, attr in enumerate(selected_attrs, start=1):
            cursor.execute("INSERT INTO Routes_Attractions (Route_ID, Attraction_ID, Number) VALUES (%s, %s, %s)",
                           (route_id, attr['id'], i))

        conn.commit()
        return f"Маршрут сохранён (ID: {route_id})"
    except Error as e:
        return f"Ошибка сохранения: {e}"
    finally:
        conn.close()

# ================== СПРАВОЧНИКИ  ==================

def get_table_info(table_name):
    """Возвращает primary_key и список столбцов (для справочников нужны только ID и Name)."""
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(f"SHOW KEYS FROM {table_name} WHERE Key_name = 'PRIMARY'")
    pk_row = cursor.fetchone()
    pk = pk_row['Column_name'] if pk_row else None
    cursor.execute(f"SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
                   (DB_CONFIG['database'], table_name))
    cols = [row['COLUMN_NAME'] for row in cursor.fetchall()]
    conn.close()
    return pk, cols

@app.callback(
    Output('dict-list-container', 'children'),
    Input('dict-type-select', 'value')
)
def load_dict_list(table_name):
    if not table_name:
        return "Выберите справочник"
    pk, cols = get_table_info(table_name)
    name_col = 'Name' if 'Name' in cols else cols[1]
    extra_cols = [c for c in cols if c not in (pk, name_col, 'Deleted')]

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        query = f"SELECT {pk}, {name_col}"
        if extra_cols:
            query += ", " + ", ".join(extra_cols)
        query += f" FROM {table_name} WHERE Deleted = 0"
        df = pd.read_sql(query, conn)
        conn.close()

        if df.empty:
            return html.Div("Нет записей")

        items = []
        for _, row in df.iterrows():
            display_text = f"{row[name_col]} (ID: {row[pk]})"
            if 'Object_Type_ID' in extra_cols and 'Object_Type_ID' in row:
                try:
                    conn2 = mysql.connector.connect(**DB_CONFIG)
                    obj_type = pd.read_sql(
                        "SELECT Name FROM Object_Types WHERE Object_Type_ID = %s AND Deleted = 0",
                        conn2, params=(row['Object_Type_ID'],)
                    )
                    if not obj_type.empty:
                        display_text += f" [Тип: {obj_type.iloc[0,0]}]"
                    conn2.close()
                except:
                    pass
            items.append(html.Div([
                html.Span(display_text),
                html.Button('Удалить', id={'type': 'dict-delete', 'table': table_name, 'id': row[pk]}),
                html.Button('Редактировать', id={'type': 'dict-edit', 'table': table_name, 'id': row[pk]})
            ], style={'margin': '5px'}))
        return html.Ul(items)
    except Error as e:
        return f"Ошибка: {e}"


@app.callback(
    Output('dict-list-container', 'children', allow_duplicate=True),
    Input({'type': 'dict-delete', 'table': ALL, 'id': ALL}, 'n_clicks'),
    State('dict-type-select', 'value'),
    prevent_initial_call=True
)
def delete_dict_entry(n_clicks_list, table_name):
    ctx = callback_context
    if not ctx.triggered:
        return dash.no_update

    triggered = ctx.triggered[0]
    if not triggered['value']:
        return dash.no_update

    triggered_prop = triggered['prop_id']
    if 'dict-delete' not in triggered_prop:
        return dash.no_update

    try:
        props = json.loads(triggered_prop.split('.')[0])
        table = props['table']
        rec_id = props['id']
    except (json.JSONDecodeError, KeyError):
        return dash.no_update

    pk, _ = get_table_info(table)
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute(f"UPDATE {table} SET Deleted = 1 WHERE {pk} = %s", (rec_id,))
    conn.commit()
    conn.close()
    return load_dict_list(table_name)


@app.callback(
    Output('dict-edit-form', 'children'),
    Input({'type': 'dict-edit', 'table': ALL, 'id': ALL}, 'n_clicks'),
    Input('dict-add-btn', 'n_clicks'),
    State('dict-type-select', 'value'),
    prevent_initial_call=True
)
def show_dict_edit_form(edit_clicks, add_clicks, table_name):
    ctx = callback_context
    if not ctx.triggered:
        return dash.no_update

    triggered = ctx.triggered[0]
    triggered_prop = triggered['prop_id']
    pk, cols = get_table_info(table_name)
    name_col = 'Name' if 'Name' in cols else cols[1]
    has_description = 'Description' in cols
    has_object_type = 'Object_Type_ID' in cols

    # --- Добавление новой записи ---
    if 'dict-add-btn' in triggered_prop and add_clicks:
        fields = [
            dcc.Store(id='dict-edit-id', data=None),
            html.Label("Название"),
            dcc.Input(id='dict-name-input', type='text'),
            html.Div([
                html.Label("Описание"),
                dcc.Textarea(          # для авторов/владельцев – многострочное поле
                    id='dict-description-input',
                    style={'width': '100%', 'height': 100}
                )
            ], style={'display': 'block' if has_description else 'none'}),
            html.Div([
                html.Label("Тип объекта"),
                dcc.Dropdown(id='dict-object-type-id', placeholder="Выберите тип объекта")
            ], style={'display': 'block' if has_object_type else 'none'}),
        ]
        if has_object_type:
            conn = mysql.connector.connect(**DB_CONFIG)
            obj_df = pd.read_sql("SELECT Object_Type_ID AS value, Name AS label FROM Object_Types WHERE Deleted = 0", conn)
            conn.close()
            options = obj_df.to_dict('records')
            fields[4] = html.Div([
                html.Label("Тип объекта"),
                dcc.Dropdown(id='dict-object-type-id', options=options, placeholder="Выберите тип объекта")
            ])
        # Кнопки Сохранить и Отмена
        fields.append(html.Div([
            html.Button('Сохранить', id='dict-save-btn'),
            html.Button('Отмена', id='dict-cancel-btn', style={'margin-left': '10px'})
        ]))
        return html.Div(fields)

    # --- Редактирование существующей записи ---
    elif 'dict-edit' in triggered_prop and triggered['value']:
        try:
            props = json.loads(triggered_prop.split('.')[0])
            table = props['table']
            rec_id = props['id']
        except (json.JSONDecodeError, KeyError):
            return dash.no_update

        columns_to_select = [pk, name_col]
        if has_description:
            columns_to_select.append("Description")
        if has_object_type:
            columns_to_select.append("Object_Type_ID")

        conn = mysql.connector.connect(**DB_CONFIG)
        df = pd.read_sql(
            f"SELECT {', '.join(columns_to_select)} FROM {table} WHERE {pk} = %s AND Deleted = 0",
            conn, params=(rec_id,)
        )
        conn.close()
        if df.empty:
            return html.Div("Запись не найдена")

        row = df.iloc[0]
        name = row[name_col]

        children = [
            dcc.Store(id='dict-edit-id', data={'table': table, 'id': rec_id, 'pk': pk}),
            html.Label("Название"),
            dcc.Input(id='dict-name-input', type='text', value=name),
            html.Div([
                html.Label("Описание"),
                dcc.Textarea(
                    id='dict-description-input',
                    value=row.get('Description', '') if has_description else '',
                    style={'width': '100%', 'height': 100}
                )
            ], style={'display': 'block' if has_description else 'none'}),
            html.Div([
                html.Label("Тип объекта"),
                dcc.Dropdown(id='dict-object-type-id', placeholder="Выберите тип объекта")
            ], style={'display': 'block' if has_object_type else 'none'}),
        ]
        if has_object_type:
            current_obj_id = row.get('Object_Type_ID', None)
            conn = mysql.connector.connect(**DB_CONFIG)
            obj_df = pd.read_sql("SELECT Object_Type_ID AS value, Name AS label FROM Object_Types WHERE Deleted = 0", conn)
            conn.close()
            options = obj_df.to_dict('records')
            children[4] = html.Div([
                html.Label("Тип объекта"),
                dcc.Dropdown(id='dict-object-type-id', options=options, value=current_obj_id)
            ])

        children.append(html.Div([
            html.Button('Сохранить', id='dict-save-btn'),
            html.Button('Отмена', id='dict-cancel-btn', style={'margin-left': '10px'})
        ]))
        return html.Div(children)

    return dash.no_update


@app.callback(
    Output('dict-edit-form', 'children', allow_duplicate=True),
    Input('dict-cancel-btn', 'n_clicks'),
    prevent_initial_call=True
)
def cancel_dict_edit(n_clicks):
    """Очищает форму редактирования при нажатии Отмена."""
    if n_clicks:
        return html.Div()
    return dash.no_update


@app.callback(
    Output('dict-list-container', 'children', allow_duplicate=True),
    Output('dict-edit-form', 'children', allow_duplicate=True),
    Input('dict-save-btn', 'n_clicks'),
    State('dict-edit-id', 'data'),
    State('dict-name-input', 'value'),
    State('dict-description-input', 'value'),
    State('dict-object-type-id', 'value'),
    State('dict-type-select', 'value'),
    prevent_initial_call=True
)
def save_dict_record(n_clicks, edit_data, name, description, object_type_id, table_name):
    if not n_clicks or not name:
        return dash.no_update, dash.no_update

    pk, cols = get_table_info(table_name)
    name_col = 'Name' if 'Name' in cols else cols[1]
    has_description = 'Description' in cols
    has_object_type = 'Object_Type_ID' in cols

    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    try:
        if edit_data:
            set_parts = [f"{name_col} = %s"]
            params = [name]
            if has_description:
                set_parts.append("Description = %s")
                params.append(description)
            if has_object_type:
                set_parts.append("Object_Type_ID = %s")
                params.append(object_type_id)
            params.append(edit_data['id'])
            cursor.execute(
                f"UPDATE {table_name} SET {', '.join(set_parts)} WHERE {edit_data['pk']} = %s AND Deleted = 0",
                params
            )
        else:
            columns = [name_col]
            placeholders = ["%s"]
            params = [name]
            if has_description:
                columns.append("Description")
                placeholders.append("%s")
                params.append(description)
            if has_object_type:
                columns.append("Object_Type_ID")
                placeholders.append("%s")
                params.append(object_type_id)
            columns.append("Deleted")
            placeholders.append("0")
            cursor.execute(
                f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({', '.join(placeholders)})",
                params
            )
        conn.commit()
    except Error as e:
        return f"Ошибка сохранения: {e}", dash.no_update
    finally:
        conn.close()
    # Обновляем список и очищаем форму
    return load_dict_list(table_name), html.Div()

#=========== Главный колбэк: переключение страниц и генерация контента ===============
@app.callback(
    Output('main-page-layout', 'style'),
    Output('attraction-page-layout', 'style'),
    Output('login-page-layout', 'style'),
    Output('admin-register-page-layout', 'style'),
    Output('admin-page-layout', 'style'),
    Output('attraction-content-holder', 'children'),
    Output('url', 'pathname', allow_duplicate=True),
    Input('map-graph', 'clickData'),
    Input('route-dropdown','value'),
    Input('url', 'pathname'),
    Input('back-to-main-btn', 'n_clicks'),
    Input('url','href'),
    prevent_initial_call=True
)
def display_page(clickData, route_id, pathname, n_clicks, href):
    """Управляет видимостью страниц и генерирует контент для страницы достопримечательности."""

    ctx = callback_context
    attraction_id = None
    
    # Если нажата кнопка "Назад", показываем главную страницу
    if ctx.triggered:
        triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]
    else:
        triggered_id=''

    hide_all = {'display': 'none'}, {'display': 'none'}, {'display': 'none'}, {'display': 'none'}, {'display': 'none'}
    main_style={'display':'none'}
    atttr_style={'display':'none'}
    login_style={'display':'none'}
    admin_reg_style={'display':'none'}

    parsed_url = urllib.parse.urlparse(href)
    query_params = urllib.parse.parse_qs(parsed_url.query)         
    
    if triggered_id == "back-to-main-btn":
        if route_id is not None and "route_id" not in query_params:
            return {'display':'block'}, {'display':'none'},{'display':'none'},{'display':'none'},{'display':'none'}, None, f"/?route_id={route_id}"
        else:
            return {'display':'block'}, {'display':'none'},{'display':'none'}, {'display':'none'},{'display':'none'}, None, "/"
    
    if pathname == '/logout':
        session.clear()
        return {'display': 'block'}, {'display': 'none'}, {'display': 'none'}, {'display': 'none'},{'display':'none'}, None, "/"

    if pathname == '/admin':
        if session.get('role') != 'admin':
            return {'display': 'block'}, {'display':'none'},{'display':'none'},{'display':'none'},{'display':'none'}, None, "/"
        return {'display':'none'},{'display':'none'},{'display':'none'},{'display':'none'},{'display':'block'}, None, pathname
    

    # Клик по карте → страница достопримечательности
    if triggered_id == "map-graph":
        if clickData:
            point = clickData.get('points',[{}])[0]

            # Проверяем, что клик был по достопримечательности (у нее есть ID)
            attraction_id = point.get('customdata')[0]
            
            if attraction_id and isinstance(attraction_id, int):
                pathname = f"/attraction/{attraction_id}"
                #return {'display':'none'}, {'display':'block'}, None, f"/attraction/{attraction_id}"
                # return {'display': 'none'}, {'display': 'block'}, {'display': 'none'}, {'display': 'none'},{'display':'none'}, None, f"/attraction/{attraction_id}"   
            
    
    # Страница логина
    if pathname == '/login':
        return {'display': 'none'}, {'display': 'none'}, {'display': 'block'}, {'display': 'none'},{'display':'none'}, None, pathname

    # Регистрация (только админ)
    if pathname == '/admin/register':
        if session.get('role') != 'admin':
            # Нет прав — перенаправляем на главную
            return {'display': 'block'}, {'display': 'none'}, {'display': 'none'}, {'display': 'none'},{'display':'none'}, None, "/"
        return {'display': 'none'}, {'display': 'none'}, {'display': 'none'}, {'display': 'block'},{'display':'none'}, None, pathname
    
    # Если URL пустой или '/', показываем главную страницу
    if pathname is None or pathname == '/' or pathname == '':
        return {'display': 'block'}, {'display': 'none'},{'display': 'none'},{'display': 'none'},{'display':'none'}, None, "/"

    # Если URL начинается с '/attraction/', пытаемся показать страницу достопримечательности
    if pathname.startswith('/attraction/'):
        
        # Извлекаем ID из URL (поддержка /attraction/3)
        path_parts = pathname.split('/')
        
        
        if len(path_parts) == 3 and path_parts[-1].isdigit():
            attraction_id = int(path_parts[-1])
        
        if attraction_id is not None:
            
            try:
                conn = mysql.connector.connect(**DB_CONFIG)
                
                # --- ЗАПРОС 1: Данные о достопримечательности ---
##                query_attr = """
##                SELECT ot.Name as Object_Type_Name,
##                c.Name as Category_Name,
##                a.*
##                FROM Attractions a
##                JOIN Object_Types ot ON a.Object_Type_ID = ot.Object_Type_ID
##                JOIN Categories c ON a.Category_ID = c.Category_ID
##                WHERE a.Attraction_ID = %s;
##                """
                query_attr = """
                    SELECT 
                        a.*,
                        ot.Name as Object_Type_Name,
                        c.Name as Category_Name,
                        ov.Name as Object_Value_Name,
                        ovs.Name as Object_Value_Status_Name,
                        tc.Name as Technical_Condition_Name,
                        os.Name as Object_Status_Name,
                        cp.Name as Creation_Purpose_Name,
                        aut.Name as Author_Name,
                        aut.Description as Author_Description,
                        own.Name as Owner_Name,
                        own.Description as Owner_Description,
                        g.Name as Geomorphology_Name,
                        rp.Name as Recreation_Potential_Name,
                        s.Name as Season_Name
                    FROM Attractions a
                    LEFT JOIN Object_Types ot ON a.Object_Type_ID = ot.Object_Type_ID
                    LEFT JOIN Categories c ON a.Category_ID = c.Category_ID
                    LEFT JOIN Object_Values ov ON a.Object_Value_ID = ov.Object_Value_ID
                    LEFT JOIN Object_Value_Statuses ovs ON a.Object_Value_Status_ID = ovs.Object_Value_Status_ID
                    LEFT JOIN Technical_Conditions tc ON a.Technical_Condition_ID = tc.Technical_Condition_ID
                    LEFT JOIN Object_Statuses os ON a.Object_Status_ID = os.Object_Status_ID
                    LEFT JOIN Creation_Purposes cp ON a.Creation_Purpose_ID = cp.Creation_Purpose_ID
                    LEFT JOIN Authors aut ON a.Author_ID = aut.Author_ID
                    LEFT JOIN Owners own ON a.Owner_ID = own.Owner_ID
                    LEFT JOIN Geomorphologies g ON a.Geomorphology_ID = g.Geomorphology_ID
                    LEFT JOIN Recreation_Potentials rp ON a.Recreation_Potential_ID = rp.Recreation_Potential_ID
                    LEFT JOIN Seasons s ON a.Season_ID = s.Season_ID
                    WHERE a.Attraction_ID = %s;
                    """
                attr_df = pd.read_sql(query_attr, conn, params=(attraction_id,), dtype=object)
                
                if attr_df.empty:
                    #error_msg = html.Div("Достопримечательность не найдена.", style={'color': 'red'})
            
                    #return {'display': 'none'}, {'display': 'block'}, error_msg, dash.no_update
                    return {'display': 'none'}, {'display': 'block'}, {'display': 'none'}, {'display': 'none'},{'display':'none'}, html.Div("Достопримечательность не найдена."), pathname
                
                row_attr = attr_df.iloc[0]
                
                # --- ЗАПРОС 2: Маршруты, к которым принадлежит достопримечательность ---
                query_routes = """
                SELECT r.Route_ID, r.Name 
                FROM Routes r 
                JOIN Routes_Attractions ra ON r.Route_ID = ra.Route_ID 
                WHERE ra.Attraction_ID = %s;
                """
                routes_df = pd.read_sql(query_routes, conn, params=(attraction_id,))
                
                routes_list_html = []
                if not routes_df.empty:
                    for _, route in routes_df.iterrows():
                        routes_list_html.append(html.Li(dcc.Link(f"{route['Name']} (ID: {route['Route_ID']})", href=f"../../?route_id={route['Route_ID']}")))
                else:
                    routes_list_html = [html.Li("Не принадлежит ни к одному маршруту.")]
                
                # --- ЗАПРОС 3: Медиа-контент (фото/видео) ---
                query_media = "SELECT Type, File_Path FROM Media WHERE Attraction_ID = %s;"
                media_df = pd.read_sql(query_media, conn, params=(attraction_id,))
                
                media_content = []
                for _, media in media_df.iterrows():
                    if media['Type'] == 'photo':
                        media_content.append(html.Img(src="../assets/"+media['File_Path'], style={'max-width': '100%', 'margin': '10px 0'}))
                    elif media['Type'] == 'video':
                        media_content.append(html.Video(src="../assets/"+media['File_Path'], controls=True, style={'max-width': '100%', 'margin': '10px 0'}))
                
                if not media_content:
                    media_content = [html.P("Медиа-контент отсутствует.")]

                aliases = {
                'Name': 'Название достопримечательности',
                'Object_Type_Name': 'Тип объекта',
                'Category_Name': 'Категория',
                'Description': 'Описание',
                'Admin_Location_ID': 'Административное расположение',
                'Latitude': 'Широта',
                'Longitude': 'Долгота',
                'Accessibility': 'Способы проезда (Доступность)',
                'City_Distance': 'Расстояние от ключевой точки',
                'History': 'Историческая справка',
                'Legends': 'Легенды',
                'Object_Value_Name': 'Значимость',
                'Object_Value_Status_Name': 'Статус значимости',
                'Object_Value_Description': 'Описание значимости',
                'Modernity': 'Благоустройство',
                'Recreation_Potential_Name': 'Рекреационный потенциал',
                'Recreation_Potential_Description': 'Описание рекреационного потенциала',
                'Season_Name': 'Сезон',
                'Time_Recommendation': 'Рекомендуемая длительность визита',
                'Visitor_Requirements': 'Требования к посетителю',
                'Rules': 'Правила',
                'Guides': 'Гиды',
                'Price': 'Цена',
                'Relief': 'Рельеф',
                'Geomorphology_Name': 'Геоморфология',
                'Geologic': 'Геологическое строение',
                'Climate': 'Климат',
                'Hydrology': 'Гидрология',
                'Flora_Fauna': 'Флора и фауна',
                'Ecologic': 'Экология',
                'Creation_Date': 'Дата создания',
                'Author_Name': 'Автор',
                'Author_Description': 'Об авторе',
                'Style_Architecture': 'Архитектурный стиль',
                'Materials_and_Technologies': 'Материалы и технологии',
                'Creation_Purpose_Name': 'Цель создания',
                'Technical_Condition_Name': 'Техническое состояние',
                'Object_Status_Name': 'Статус объекта',
                'Owner_Name': 'Владелец',
                'Owner_Description': 'О владельце',
                'Restoration_Works': 'Реставрационные работы',
                'TCI': 'Климатический индекс'
            }
                
                # --- СОБИРАЕМ HTML ДЛЯ СТРАНИЦЫ ДОСТОПРИМЕЧАТЕЛЬНОСТИ ---
                
                # Блок с информацией о достопримечательности
                attr_info_content = []

                # Получаем тип объекта из данных
                object_type = row_attr.get("Object_Type_ID")
                
                for col in attr_df.columns:
                    if col in ['Deleted','Attraction_ID', 'Latitude', 'Longitude'] or "_ID" in col and col not in ["Admin_Location_ID", "Key_City_ID"]:#, 'Object_Type_ID', 'Category_ID']:
                        continue
                    value = row_attr.get(col)
                    display_name = aliases.get(col, col.replace('_', ' ').title())
                    if col == "Admin_Location_ID":
                        display_name = "Административное расположение"
                        if value is not None and value != '':
                            value = bring_address(conn.cursor(dictionary=True), value)
                        else:
                            continue
                    elif col == "Key_City_ID":
                        display_name = "Ключевая точка"
                        if value is not None and value != '':
                            value = bring_address(conn.cursor(dictionary=True), value)
                        else:
                            continue
                    #Convert IDs to exact values

                    
                    

                    # --- УСЛОВИЕ 1: ЕСЛИ ОБЪЕКТ ПРИРОДНЫЙ ---
                    # Скрываем поля, относящиеся к антропогенным объектам

                    if object_type == "1":
                        fields_to_hide_for_natural = [
                            'Creation_Date', 'Author_Name', 'Author_Description',
                                                  'Style_Architecture', 'Materials_and_Technologies',
                                                  'Creation_Purpose_Name', 'Technical_Condition_Name',
                                                  'Object_Status_Name', 'Owner_Name', 'Owner_Description',
                                                  'Restoration_Works'

                            ]
                        if col in fields_to_hide_for_natural:
                            continue # Пропускаем итерацию, не добавляем это поле

                    # --- УСЛОВИЕ 2: ЕСЛИ ОБЪЕКТ АНТРОПОГЕННЫЙ ---
                    if object_type == "2":
                        fields_to_hide_for_anthropogenic = [
                            'Relief','Geomorphology_Name', 'Geologic', 'Climate', 'Hydrology', 'Flora_Fauna', 'Ecologic'
                        ]
                        if col in fields_to_hide_for_anthropogenic:
                            continue # Пропускаем итерацию

                    # 4. Проверка на пустое значение (исправленная логика)
                    if value is None or (isinstance(value, float) and pd.isna(value)) or (isinstance(value, str) and value.strip() == ''):
                        continue # Не выводим пустые поля
                        
                    value_str = str(value).replace('\n', '<br>')
                    attr_info_content.append(html.Div([
                        html.B(f"{display_name}:"),
                        html.Div(dcc.Markdown(value_str), style={'margin-left': '10px'})
                    ], style={'margin': '15px 0'}))
                
                # Карта с точкой достопримечательности
                map_fig = go.Figure(go.Scattermapbox(
                    lat=[row_attr['Latitude']],
                    lon=[row_attr['Longitude']],
                    mode='markers',
                    marker=go.scattermapbox.Marker(size=14, color='red'),
                    text=[row_attr['Name']],
                    hoverinfo='text'
                ))
                
                map_fig.update_layout(
                    mapbox_style="open-street-map",
                    mapbox_zoom=12,
                    mapbox_center_lat=row_attr['Latitude'],
                    mapbox_center_lon=row_attr['Longitude'],
                    margin={"r":0,"t":0,"l":0,"b":0},
                    height=450
                )
                
                full_attraction_page_html = html.Div([
                    html.H2(f"Информация о достопримечательности: {row_attr.get('Name', '')}"),
                    
                    html.Div([
                        # Левый блок: Информация и Медиа
                        html.Div([
                            html.Div(attr_info_content),
                            
                            html.H4("Медиа-контент:", style={'margin-top': '30px'}),
                            html.Div(media_content),
                        ], style={'width': '65%', 'display': 'inline-block'}),
                        
                        # Правый блок: Карта и Список маршрутов
                        html.Div([
                            dcc.Graph(figure=map_fig),
                            
                            html.H4("Входит в маршруты:", style={'margin-top': '30px'}),
                            html.Ul(routes_list_html),
                        ], style={'width': '35%', 'display': 'inline-block', 'padding-left': '20px'})
                    ])
                ])
                

                # Генерация QR-кода
                qr_block = html.Div()
                if attraction_id and href:
                    try:
                        parsed = urllib.parse.urlparse(href)
                        base_url = f"{parsed.scheme}://{parsed.netloc}"
                        attraction_url = f"{base_url}/attraction/{attraction_id}"

                        qr = qrcode.QRCode(version=1, box_size=6, border=2)
                        qr.add_data(attraction_url)
                        qr.make(fit=True)
                        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

                        from PIL import ImageDraw, ImageFont, Image
                        width, height = qr_img.size
                        new_height = height + 30
                        combined = Image.new("RGB", (width, new_height), "white")
                        combined.paste(qr_img, (0, 0))

                        draw = ImageDraw.Draw(combined)
                        try:
                            font = ImageFont.truetype("arial.ttf", 12)
                        except:
                            font = ImageFont.load_default()
                        text = attraction_url
                        bbox = draw.textbbox((0, 0), text, font=font)
                        text_width = bbox[2] - bbox[0]
                        text_x = (width - text_width) // 2
                        draw.text((text_x, height + 5), text, fill="black", font=font)

                        buffer = io.BytesIO()
                        combined.save(buffer, format="PNG")
                        img_str = base64.b64encode(buffer.getvalue()).decode("utf-8")

                        qr_block = html.Div([
                            html.Img(src=f"data:image/png;base64,{img_str}", style={"width": "160px", "display": "block", "margin": "0 auto"})
                        ], style={"textAlign": "center", "marginBottom": "20px"})
                    except Exception as e:
                        qr_block = html.Div(f"Ошибка QR-кода: {e}")

                # Добавляем QR-код в начало страницы
                full_attraction_page_html = html.Div([qr_block, full_attraction_page_html])

                return {'display': 'none'}, {'display': 'block'},{'display': 'none'}, {'display': 'none'},{'display':'none'}, full_attraction_page_html, pathname

            except Error as e:
                error_msg = html.Div(f"Ошибка базы данных: {e}", style={'color': 'red'})
                return {'display': 'none'}, {'display': 'block'},{'display': 'none'}, {'display': 'none'},{'display':'none'}, error_msg, pathname
            finally:
                if 'conn' in locals() and conn.is_connected():
                    conn.close()
    
    # Если URL не распознан, показываем главную страницу (или можно показать 404)
    return {'display': 'block'}, {'display': 'none'}, {'display': 'none'}, {'display': 'none'},{'display':'none'}, None, "/"



            


if __name__ == '__main__':
    app.run_server(debug=os.getenv('DEBUG', 'False').lower() == 'true')
