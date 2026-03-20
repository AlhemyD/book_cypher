import dash
from dash import dcc, html, Input, Output, callback, dash, callback_context
import pandas as pd
import plotly.graph_objects as go
import mysql.connector
from mysql.connector import Error
import urllib.parse

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

# --- НАСТРОЙКИ ПОДКЛЮЧЕНИЯ К БД ---
DB_CONFIG = {
    'host': 'localhost',
    'database': 'travel_db',
    'user': 'yuji',
    'password': '5423'
}

# --- ИНИЦИАЛИЗАЦИЯ DASH ПРИЛОЖЕНИЯ ---
app = dash.Dash(__name__)
server = app.server

# --- ГЕНЕРАЦИЯ ЛЕЙАУТА ---
app.layout = html.Div([
    dcc.Location(id='url', refresh=False), # Основной компонент навигации
    html.Div(id='main-page-layout', style={'display':'block'}, children=
    [html.H1("Визуализация туристических маршрутов", style={'textAlign': 'center'}),

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
        html.Button("← Назад к маршрутам", id='back-to-main-btn', n_clicks=0, style={'margin-bottom': '20px'}),
        
        # Здесь будет динамически генерироваться контент
        html.Div(id='attraction-content-holder'),
    ]),
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

# 2. Загружаем данные о маршрутах И фильтруем их по выбранной локации
@app.callback(
    Output('route-dropdown', 'options'),
    Output('routes-meta-store', 'data'), # Сохраняем отфильтрованные данные
    Input('location-filter', 'value'),
    Input('routes-meta-store', 'data'), # Используем как State, чтобы не загружать заново
)
def filter_routes_by_location(selected_location_id, stored_routes_data):
    # Если данные уже есть в хранилище, используем их, чтобы не делать лишний запрос
    if stored_routes_data and selected_location_id:
        df_routes = pd.DataFrame(stored_routes_data)
    else:
        # Если данных нет, загружаем их из БД
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            query = "SELECT Route_ID, Name, Admin_Location_ID FROM Routes;"
            df_routes = pd.read_sql(query, conn)
        except Error as e:
            print(f"Ошибка при загрузке маршрутов: {e}")
            return [], None
    
    if df_routes.empty:
        return [], None

    # --- ФИЛЬТРАЦИЯ ---
    # Находим саму выбранную локацию и всех её "детей" (подчиненные районы, села)
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        
        # Запрос для поиска всех подчиненных локаций (включая саму себя)
        query_locations = """
        WITH RECURSIVE loc_tree AS (
            SELECT Admin_Location_ID FROM Admin_Location WHERE Admin_Location_ID = %s
            UNION ALL
            SELECT al.Admin_Location_ID 
            FROM Admin_Location al
            INNER JOIN loc_tree lt ON al.Parent_ID = lt.Admin_Location_ID
        )
        SELECT Admin_Location_ID FROM loc_tree;
        """
        loc_df = pd.read_sql(query_locations, conn, params=(selected_location_id,))
        
        # Если запрос к локациям прошел успешно, фильтруем маршруты
        if not loc_df.empty:
            valid_location_ids = loc_df['Admin_Location_ID'].tolist()
            
            # Фильтруем маршруты, у которых Admin_Location_ID есть в списке найденных локаций
            filtered_routes = df_routes[df_routes['Admin_Location_ID'].isin(valid_location_ids)]
            
            options = [
                {'label': row['Name'], 'value': row['Route_ID']}
                for _, row in filtered_routes.iterrows()
            ]
            
            return options, filtered_routes.to_dict('records')
            
    except Error as e:
        print(f"Ошибка при фильтрации по локации: {e}")
    
    # Если что-то пошло не так или фильтрация не удалась, показываем все маршруты
    options = [
        {'label': row['Name'], 'value': row['Route_ID']}
        for _, row in df_routes.iterrows()
    ]
    return options, df_routes.to_dict('records')


# 3. Читаем ID маршрута из URL и устанавливаем его в Dropdown
@app.callback(
    Output('route-dropdown', 'value'),
    Input('url', 'href'),
    Input('route-dropdown', 'options'), # Чтобы не срабатывало до загрузки списка
)
def set_dropdown_value_from_url(href, options):
    if not options or not href:
        return None

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
    return None

# 4. Главная функция: обновляем карту и информацию при выборе маршрута
@app.callback(
    Output('map-graph', 'figure'),
    Output('route-info-container', 'children'),
    Input('route-dropdown', 'value'),
    Input('routes-data-store', 'data')
)
def update_map_and_info(selected_route_id, geo_data):
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
    
    # Линия маршрута
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
    ]
    
    # Точки (маркеры)
    fig.add_trace(go.Scattermapbox(
        lat=attractions_df['lat'],
        lon=attractions_df['lon'],
        mode='markers',

        text = attractions_df["Attraction_Name"],

        customdata=attractions_df["Attraction_ID"],
        # --- НАСТРОЙКА ПОДСКАЗОК (TOOLTIP) ---
        hovertemplate="<b>ID: %{customdata}</b><br>" +
                      "<br>%{text}<br>"+
                      "Широта: %{lat}<br>" +
                      "Долгота: %{lon}<br>" +
                      "<extra></extra>",
        
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

    fig.add_trace(go.Scattermapbox(
        lat=start_finish_df['lat'],
        lon=start_finish_df['lon'],
        mode='markers',
        
        # У этих точек НЕТ customdata, поэтому по ним нельзя будет кликнуть для перехода
        
        marker=dict(size=12, color='green'), 
        # Зеленый цвет, чтобы визуально отличить от красных достопримечательностей
        
        hovertemplate="<b>%{text}</b><extra></extra>",
        
        text=start_finish_df['Attraction_Name'],
        name='Точки старта/финиша',
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
        query = "SELECT * FROM Routes WHERE Route_ID = %s;"
        
        info_df = pd.read_sql(query, conn, params=(selected_route_id,), dtype=object)
         
        if not info_df.empty:
            row = info_df.iloc[0]
             
            # Динамически создаем HTML-блок со всеми полями из таблицы
            content = []
            for idx, col in enumerate(info_df.columns):
                # Приводим имена к красивому виду и пропускаем технические ID
                display_name = col.replace('_', ' ').title()
                value = row[col]
                if col in ['Start_Point_Latitude','Start_Point_Longitude', 'End_Point_Latitude', 'End_Point_Longitude']:
                    continue

                if col in ['Admin_Location_ID']:
                    display_name = "Admin Location Name"
                    value = bring_address(conn.cursor(dictionary=True), value)
                
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
             
    except Error as e:
        print(f"Ошибка при получении информации о маршруте: {e}")
        info_html = html.Div("Ошибка загрузки информации о маршруте.")
    finally:
        if conn.is_connected():
            conn.close()
             
    return fig, info_html

### Колбэк для навигации по клику на карту (меняет URL)
##@app.callback(
##    Output('url', 'pathname'),
##    Input('map-graph', 'clickData'),
##    Input('route-dropdown','value'),
##    prevent_initial_call=True
##)
##def navigate_on_click(clickData, route_id):
##    if clickData:
##        point = clickData.get('points', [{}])[0]
##        
##        # Проверяем, что клик был по достопримечательности (у нее есть ID)
##        attraction_id = point.get('customdata')
##        
##        if attraction_id and isinstance(attraction_id, int):
##            return f"/attraction/{attraction_id}"
##            
##    return dash.no_update

# Главный колбэк: переключение страниц и генерация контента
@app.callback(
    Output('main-page-layout', 'style'),
    Output('attraction-page-layout', 'style'),
    Output('attraction-content-holder', 'children'),
    Output('url', 'pathname'),
    Input('map-graph', 'clickData'),
    Input('route-dropdown','value'),
    Input('url', 'pathname'),
    Input('back-to-main-btn', 'n_clicks'),
    prevent_initial_call=True
)
def display_page(clickData, route_id, pathname, n_clicks):
    """Управляет видимостью страниц и генерирует контент для страницы достопримечательности."""

    ctx = callback_context
    attraction_id = None
    
    # Если нажата кнопка "Назад", показываем главную страницу
    #if ctx.triggered:
    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]
    if triggered_id == "back-to-main-btn":
        if pathname.split("?")==1 and route_id is not None:
            return {'display':'block'}, {'display':'none'}, None, f"/?route_id={route_id}"
        else:
            return {'display':'block'}, {'display':'none'}, None, "/"
    if triggered_id == "map-graph":
        if clickData:
            point = clickData.get('points',[{}])[0]

            # Проверяем, что клик был по достопримечательности (у нее есть ID)
            attraction_id = point.get('customdata')
            
            if attraction_id and isinstance(attraction_id, int):
                pathname = f"/attraction/{attraction_id}"
                #return {'display':'none'}, {'display':'block'}, None, f"/attraction/{attraction_id}"
                    
            
    
    
    # Если URL пустой или '/', показываем главную страницу
    if pathname is None or pathname == '/' or pathname == '':
        return {'display': 'block'}, {'display': 'none'}, None, "/"

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
                query_attr = """
                SELECT ot.Name as Object_Type_Name,
                c.Name as Category_Name,
                a.*
                FROM Attractions a
                JOIN Object_Types ot ON a.Object_Type_ID = ot.Object_Type_ID
                JOIN Categories c ON a.Category_ID = c.Category_ID
                WHERE a.Attraction_ID = %s;
                """
                attr_df = pd.read_sql(query_attr, conn, params=(attraction_id,), dtype=object)
                
                if attr_df.empty:
                    error_msg = html.Div("Достопримечательность не найдена.", style={'color': 'red'})
                    return {'display': 'none'}, {'display': 'block'}, error_msg, dash.no_update
                
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
                
                # --- СОБИРАЕМ HTML ДЛЯ СТРАНИЦЫ ДОСТОПРИМЕЧАТЕЛЬНОСТИ ---
                
                # Блок с информацией о достопримечательности
                attr_info_content = []

                # Получаем тип объекта из данных
                object_type = row_attr.get("Object_Type_ID")
                
                for col in attr_df.columns:
                    if col in ['Attraction_ID', 'Latitude', 'Longitude', 'Object_Type_ID', 'Category_ID']:
                        continue
                    value = row_attr.get(col)
                    display_name = col.replace('_', ' ')
                    if col == "Admin_Location_ID":
                        display_name = "Admin Location"
                        value = bring_address(conn.cursor(dictionary=True),value)
                    #Convert IDs to exact values

                    
                    

                    # --- УСЛОВИЕ 1: ЕСЛИ ОБЪЕКТ ПРИРОДНЫЙ ---
                    # Скрываем поля, относящиеся к антропогенным объектам

                    if object_type == "1":
                        fields_to_hide_for_natural = [
                            'Creation Date', 'Author', 'Style Architecture', 'Materials And Technologies',
                            'Creation Purpose', 'Technical Condition', 'Object Status', 'Owner', 'Restoration Works'
                        ]
                        if display_name in fields_to_hide_for_natural:
                            continue # Пропускаем итерацию, не добавляем это поле

                    # --- УСЛОВИЕ 2: ЕСЛИ ОБЪЕКТ АНТРОПОГЕННЫЙ ---
                    if object_type == "2":
                        fields_to_hide_for_anthropogenic = [
                            'Geomorphology', 'Geologic', 'Climate', 'Hydrology', 'Flora Fauna', 'Ecologic'
                        ]
                        if display_name in fields_to_hide_for_anthropogenic:
                            continue # Пропускаем итерацию

                    # 4. Проверка на пустое значение (исправленная логика)
                    is_empty = False
                    if value is None:
                        is_empty = True
                    elif isinstance(value, float) and pd.isna(value):
                        is_empty = True
                    elif isinstance(value, str) and value.strip() == '':
                        is_empty = True

                    if is_empty:
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
                
                return {'display': 'none'}, {'display': 'block'}, full_attraction_page_html, f"/attraction/{attraction_id}"

            except Error as e:
                error_msg = html.Div(f"Ошибка базы данных: {e}", style={'color': 'red'})
                return {'display': 'none'}, {'display': 'block'}, error_msg, dash.no_update
            finally:
                if conn.is_connected():
                    conn.close()
    
    # Если URL не распознан, показываем главную страницу (или можно показать 404)
    return {'display': 'block'}, {'display': 'none'}, None, "/"



            


if __name__ == '__main__':
    app.run_server(debug=True)
