import sys
import a2s
import asyncio
import webbrowser
import json
import socket
import pyperclip
import base64
import logging
import inspect
from datetime import datetime
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTreeWidget, QTreeWidgetItem, QMenu, QAction,
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout,
    QMessageBox, QInputDialog, QSystemTrayIcon, QStyle, QWidget,
    QListWidget, QListWidgetItem, QGroupBox, QSplitter, QAbstractItemView,
    QHeaderView
)
from PyQt5.QtCore import Qt, QTimer, QObject, pyqtSignal, QCoreApplication, QByteArray, QMimeData
from PyQt5.QtGui import QIcon, QDrag
import qasync

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('server_monitor.log', encoding='utf-8')
    ]
)
logger = logging.getLogger('ServerMonitor')

LOCALE_DIR = Path(__file__).parent / 'locales'
CONFIG_FILE = Path(__file__).parent / 'config.json'
DEFAULT_LANGUAGE = 'ru_RU'
DEFAULT_UPDATE_INTERVAL = 30
DEFAULT_SERVERS = [
    '45.136.205.69:27015'
]

class ConfigManager:
    def __init__(self):
        self.config = {
            'language': DEFAULT_LANGUAGE,
            'update_interval': DEFAULT_UPDATE_INTERVAL,
            'servers': DEFAULT_SERVERS.copy(),
            'visible_columns': ['server', 'online', 'ip_port', 'map', 'platform', 'ping'],
            'column_widths': {},
            'window_geometry': None
        }
        self.load_config()

    def load_config(self):
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, 'r') as f:
                    loaded_config = json.load(f)
                    
                    if 'window_geometry' in loaded_config and loaded_config['window_geometry']:
                        try:
                            self.config['window_geometry'] = QByteArray.fromBase64(
                                loaded_config['window_geometry'].encode('utf-8'))
                        except Exception as e:
                            logger.error(f"Geometry decode error: {e}")
                            self.config['window_geometry'] = None
                    else:
                        self.config['window_geometry'] = None
                    
                    self.config.update({
                        'language': loaded_config.get('language', DEFAULT_LANGUAGE),
                        'update_interval': loaded_config.get('update_interval', DEFAULT_UPDATE_INTERVAL),
                        'servers': loaded_config.get('servers', DEFAULT_SERVERS.copy()),
                        'visible_columns': loaded_config.get('visible_columns', self.config['visible_columns']),
                        'column_widths': loaded_config.get('column_widths', {}),
                    })
        except Exception as e:
            logger.error(f"Config load error: {e}")
            self.save_config()

    def save_config(self):
        try:
            save_config = self.config.copy()
            
            if save_config['window_geometry']:
                save_config['window_geometry'] = base64.b64encode(
                    save_config['window_geometry']).decode('utf-8')
            else:
                save_config['window_geometry'] = None
            
            with open(CONFIG_FILE, 'w') as f:
                json.dump(save_config, f, indent=2)
        except Exception as e:
            logger.error(f"Config save error: {e}")

    @property
    def language(self):
        return self.config['language']
    
    @language.setter
    def language(self, value):
        self.config['language'] = value
    
    @property
    def update_interval(self):
        return self.config['update_interval']
    
    @update_interval.setter
    def update_interval(self, value):
        self.config['update_interval'] = value
    
    @property
    def servers(self):
        return self.config['servers']
    
    @servers.setter
    def servers(self, value):
        self.config['servers'] = value
    
    @property
    def visible_columns(self):
        return self.config['visible_columns']
    
    @visible_columns.setter
    def visible_columns(self, value):
        self.config['visible_columns'] = value
    
    @property
    def column_widths(self):
        return self.config['column_widths']
    
    def set_column_width(self, column_id, width):
        self.config['column_widths'][column_id] = width
    
    @property
    def window_geometry(self):
        return self.config['window_geometry']
    
    @window_geometry.setter
    def window_geometry(self, value):
        self.config['window_geometry'] = value

config_manager = ConfigManager()

class Localization:
    def __init__(self, config):
        self.config = config
        self.strings = {}
        self.languages = self.find_languages()
        self.load_language(self.config.language)

    def find_languages(self):
        """Находит все доступные языки в папке локализаций"""
        languages = {}
        if LOCALE_DIR.exists():
            for file in LOCALE_DIR.glob('*.json'):
                try:
                    with open(file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        lang_name = data.get("lang", file.stem)
                        languages[file.stem] = lang_name
                except Exception as e:
                    logger.error(f"Error reading language file {file}: {e}")
        return languages

    def load_language(self, lang_code):
        try:
            file_path = LOCALE_DIR / f'{lang_code}.json'
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.strings = json.load(f)
            else:
                logger.error(f"Language file not found: {file_path}")
                self.strings = {}
        except Exception as e:
            logger.error(f"Language load error: {e}")
            self.strings = {}

localization = Localization(config_manager)

def tr(key):
    return localization.strings.get(key, key)

def is_css_v34(version):
    return str(version) == '1.0.0.34'

class AsyncUpdater(QObject):
    server_updated = pyqtSignal(str, dict)
    update_completed = pyqtSignal()
    update_started = pyqtSignal()
    
    def __init__(self, server_list):
        super().__init__()
        self.server_list = server_list
        self.tasks = []
        self.running = False
        self._update_task = None

    async def fetch_server_data(self, server):
        try:
            address, port = server.split(':')
            address_tuple = (address, int(port))
            
            # Создаем задачи для параллельного выполнения
            info_task = asyncio.create_task(a2s.ainfo(address_tuple, timeout=3))
            players_task = asyncio.create_task(a2s.aplayers(address_tuple, timeout=5))
            rules_task = asyncio.create_task(a2s.arules(address_tuple, timeout=3))
            
            # Ожидаем завершения с обработкой таймаутов
            try:
                info = await asyncio.wait_for(info_task, timeout=5)
            except (asyncio.TimeoutError, ConnectionRefusedError):
                info = None
            except Exception as e:
                logger.warning(f"Info error for {server}: {e}")
                info = None
                
            try:
                players = await asyncio.wait_for(players_task, timeout=5)
            except (asyncio.TimeoutError, ConnectionRefusedError):
                players = []
            except Exception as e:
                logger.warning(f"Players error for {server}: {e}")
                players = []
                
            try:
                rules = await asyncio.wait_for(rules_task, timeout=5)
            except (asyncio.TimeoutError, ConnectionRefusedError):
                rules = {}
            except Exception as e:
                logger.warning(f"Rules error for {server}: {e}")
                rules = {}
            
            logger.debug(f"Fetched data for {server}: info={info is not None}, players={len(players)}, rules={len(rules)}")
            return {
                'server': server,
                'info': info,
                'players': players,
                'rules': rules
            }
        except Exception as e:
            logger.error(f"General error for {server}: {e}")
            return {
                'server': server,
                'info': None,
                'players': [],
                'rules': {}
            }

    async def update_all_servers(self):
        if self.running:
            return
            
        self.running = True
        self.update_started.emit()
        
        try:
            # Создаем задачи для всех серверов
            self.tasks = [self.fetch_server_data(server) for server in self.server_list]
            
            # Обрабатываем результаты по мере их поступления
            for task in asyncio.as_completed(self.tasks):
                try:
                    data = await task
                    self.server_updated.emit(data['server'], data)
                except asyncio.CancelledError:
                    logger.info("Update task cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error processing task: {e}")
        finally:
            self.running = False
            self.update_completed.emit()
            self.tasks = []
            logger.debug("Update completed")

    def cancel_updates(self):
        if self._update_task and not self._update_task.done():
            self._update_task.cancel()
            logger.info("Updates cancelled")

class DraggableListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDrop)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return
            
        mime_data = QMimeData()
        mime_data.setText(item.text())
        mime_data.setData("application/x-column-id", item.data(Qt.UserRole).encode('utf-8'))
        
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec_(Qt.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-column-id"):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-column-id"):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.source() == self:
            super().dropEvent(event)
            return
            
        if event.mimeData().hasFormat("application/x-column-id"):
            col_id = event.mimeData().data("application/x-column-id").data().decode('utf-8')
            col_name = event.mimeData().text()
            
            # Проверяем, существует ли уже такой элемент
            for i in range(self.count()):
                if self.item(i).data(Qt.UserRole) == col_id:
                    return
                    
            # Создаем новый элемент
            new_item = QListWidgetItem(col_name)
            new_item.setData(Qt.UserRole, col_id)
            self.addItem(new_item)
            
            # Удаляем элемент из источника, если это другой виджет
            if event.source() and event.source() != self:
                source = event.source()
                for i in range(source.count()):
                    if source.item(i).data(Qt.UserRole) == col_id:
                        source.takeItem(i)
                        break
            
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

class ServerMonitorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.server_list = config_manager.servers.copy()
        self.update_interval = config_manager.update_interval
        self.last_update = None
        self.selected_server = None
        self.server_items = {}
        self.players_data = {}
        self.server_info_data = {}
        self.server_info_objects = {}  # Для хранения полных объектов a2s.ServerInfo
        self.rules_data = {}
        self.tray_icon = None
        self.async_updater = AsyncUpdater(self.server_list)
        self.update_timer = QTimer()
        self.real_exit = False
        
        # Собираем все атрибуты ServerInfo и ключи правил
        self.all_info_attributes = set()
        self.all_rule_keys = set()
        
        # Флаг для отслеживания ручного изменения ширины
        self.manual_column_resize = False
        self.column_resize_timer = QTimer()
        self.column_resize_timer.setSingleShot(True)
        self.column_resize_timer.timeout.connect(self.handle_column_resize_timeout)
        
        self.column_definitions = self.create_column_definitions()
        
        self.setup_ui()
        self.setup_tray_icon()
        self.setup_signals()
        self.initial_populate()
        
        if config_manager.window_geometry:
            self.restoreGeometry(config_manager.window_geometry)
    
    def create_column_definitions(self):
        """Создает динамические определения колонок на основе всех известных атрибутов"""
        column_defs = {}
        
        # Основные предопределенные колонки
        predefined_columns = {
            'server': {
                'name': tr("server"),
                'min_width': 150,
                'default_width': 200,
                'getter': lambda s: self.server_info_data.get(s, {}).get('server_name', tr("connection_error"))
            },
            'online': {
                'name': tr("online"),
                'min_width': 80,
                'default_width': 100,
                'getter': lambda s: f"{self.server_info_data.get(s, {}).get('player_count', 0)}/{self.server_info_data.get(s, {}).get('max_players', 0)}"
            },
            'ip_port': {
                'name': tr("ip_port"),
                'min_width': 120,
                'default_width': 150,
                'getter': lambda s: s
            },
            'map': {
                'name': tr("map"),
                'min_width': 120,
                'default_width': 150,
                'getter': lambda s: self.server_info_data.get(s, {}).get('map_name', 'N/A')
            },
            'platform': {
                'name': tr("platform"),
                'min_width': 150,
                'default_width': 200,
                'getter': lambda s: f"{self.server_info_data.get(s, {}).get('app_id', '')}, {self.server_info_data.get(s, {}).get('version', '')}"
            },
            'ping': {
                'name': tr("ping"),
                'min_width': 60,
                'default_width': 80,
                'getter': lambda s: f"{self.server_info_data.get(s, {}).get('ping', 0)*1000:.0f} ms"
            },
            'players_count': {
                'name': tr("players_count"),
                'min_width': 80,
                'default_width': 100,
                'getter': lambda s: str(len(self.players_data.get(s, [])))
            },
            'bots_count': {
                'name': tr("bots_count"),
                'min_width': 60,
                'default_width': 80,
                'getter': lambda s: str(len([p for p in self.players_data.get(s, []) if p.name.startswith('bot')]))
            },
            'vac': {
                'name': tr("vac"),
                'min_width': 60,
                'default_width': 80,
                'getter': lambda s: tr("enabled") if self.server_info_data.get(s, {}).get('vac_enabled', False) else tr("disabled")
            },
            'server_os': {
                'name': tr("server_os"),
                'min_width': 100,
                'default_width': 120,
                'getter': lambda s: self.server_info_data.get(s, {}).get('server_os', 'N/A')
            },
            'folder': {
                'name': tr("folder"),
                'min_width': 120,
                'default_width': 150,
                'getter': lambda s: self.server_info_data.get(s, {}).get('folder', 'N/A')
            },
            'steam_id': {
                'name': tr("steam_id"),
                'min_width': 120,
                'default_width': 150,
                'getter': lambda s: self.server_info_data.get(s, {}).get('steam_id', 'N/A')
            },
            'keywords': {
                'name': tr("keywords"),
                'min_width': 150,
                'default_width': 200,
                'getter': lambda s: self.server_info_data.get(s, {}).get('keywords', 'N/A')
            },
            'port': {
                'name': tr("port"),
                'min_width': 60,
                'default_width': 80,
                'getter': lambda s: str(self.server_info_data.get(s, {}).get('port', 'N/A'))
            },
            'version': {
                'name': tr("version"),
                'min_width': 100,
                'default_width': 120,
                'getter': lambda s: self.server_info_data.get(s, {}).get('version', 'N/A')
            },
            'maxrate': {
                'name': tr("max_rate"),
                'min_width': 80,
                'default_width': 100,
                'getter': lambda s: self.rules_data.get(s, {}).get('sv_maxrate', 'N/A')
            },
            'minrate': {
                'name': tr("min_rate"),
                'min_width': 80,
                'default_width': 100,
                'getter': lambda s: self.rules_data.get(s, {}).get('sv_minrate', 'N/A')
            },
            'maxupdaterate': {
                'name': tr("max_upd_rate"),
                'min_width': 100,
                'default_width': 120,
                'getter': lambda s: self.rules_data.get(s, {}).get('sv_maxupdaterate', 'N/A')
            },
            'minupdaterate': {
                'name': tr("min_upd_rate"),
                'min_width': 100,
                'default_width': 120,
                'getter': lambda s: self.rules_data.get(s, {}).get('sv_minupdaterate', 'N/A')
            },
            'maxcmdrate': {
                'name': tr("max_cmd_rate"),
                'min_width': 100,
                'default_width': 120,
                'getter': lambda s: self.rules_data.get(s, {}).get('sv_maxcmdrate', 'N/A')
            },
            'mincmdrate': {
                'name': tr("min_cmd_rate"),
                'min_width': 100,
                'default_width': 120,
                'getter': lambda s: self.rules_data.get(s, {}).get('sv_mincmdrate', 'N/A')
            },
            'region': {
                'name': tr("region"),
                'min_width': 80,
                'default_width': 100,
                'getter': lambda s: self.rules_data.get(s, {}).get('sv_region', 'N/A')
            },
            'contact': {
                'name': tr("contact"),
                'min_width': 120,
                'default_width': 150,
                'getter': lambda s: self.rules_data.get(s, {}).get('sv_contact', 'N/A')
            },
            'players_list': {
                'name': tr('players_list'),
                'min_width': 300,
                'default_width': 350,
                'getter': lambda s: ', '.join([p.name for p in self.players_data.get(s, [])[:3]]) + ('...' if len(self.players_data.get(s, [])) > 3 else '')
            },
            'rules_list': {
                'name': tr('rules_list'),
                'min_width': 300,
                'default_width': 350,
                'getter': lambda s: ', '.join([f"{k}={v}" for k, v in list(self.rules_data.get(s, {}).items())[:3]]) + ('...' if len(self.rules_data.get(s, {})) > 3 else '')
            }
        }
        
        # Добавляем предопределенные колонки
        for col_id, col_def in predefined_columns.items():
            column_defs[col_id] = col_def
        
        # Динамические колонки для атрибутов ServerInfo
        for attr in self.all_info_attributes:
            col_id = f"info_{attr}"
            column_defs[col_id] = {
                'name': f"{attr}",
                'min_width': 100,
                'default_width': 150,
                'getter': lambda s, attr=attr: self.get_info_attribute(s, attr)
            }
        
        # Динамические колонки для правил
        for key in self.all_rule_keys:
            col_id = f"rule_{key}"
            column_defs[col_id] = {
                'name': f"{key}",
                'min_width': 100,
                'default_width': 150,
                'getter': lambda s, key=key: self.get_rule_value(s, key)
            }
            
        return column_defs
    
    def get_info_attribute(self, server, attr):
        """Возвращает значение атрибута из ServerInfo"""
        if server in self.server_info_objects:
            try:
                value = getattr(self.server_info_objects[server], attr)
                
                # Специальная обработка для некоторых типов данных
                if isinstance(value, bool):
                    return tr("true") if value else tr("false")
                elif isinstance(value, (list, tuple)):
                    return ', '.join(map(str, value))
                elif isinstance(value, bytes):
                    return value.decode('utf-8', errors='ignore')
                return str(value)
            except AttributeError:
                return "N/A"
        return "N/A"
    
    def get_rule_value(self, server, key):
        """Возвращает значение правила"""
        return self.rules_data.get(server, {}).get(key, "N/A")

    def setup_ui(self):
        self.setWindowTitle(tr("server_monitor"))
        self.setGeometry(100, 100, 1000, 600)
        
        # Central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Create tree widget
        self.tree = QTreeWidget()
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.tree.setSortingEnabled(True)
        self.tree.setSelectionMode(QTreeWidget.SingleSelection)
        
        # Настраиваем растяжение колонок
        self.tree.header().setSectionResizeMode(QHeaderView.Interactive)
        self.tree.header().setStretchLastSection(False)
        self.tree.setSizeAdjustPolicy(QTreeWidget.AdjustToContents)
        
        # Подключаем обработчик ручного изменения ширины колонок
        self.tree.header().sectionResized.connect(self.handle_column_resized)
        
        # Контекстное меню для заголовков
        self.tree.header().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.header().customContextMenuRequested.connect(self.show_header_context_menu)
        
        main_layout.addWidget(self.tree)
        
        # Control buttons
        control_layout = QHBoxLayout()
        
        self.add_button = QPushButton(tr("add_server"))
        self.add_button.clicked.connect(self.add_server_dialog)
        control_layout.addWidget(self.add_button)
        
        self.refresh_button = QPushButton(tr("refresh_now"))
        self.refresh_button.setEnabled(True)
        self.refresh_button.clicked.connect(self.force_update)
        control_layout.addWidget(self.refresh_button)
        
        self.settings_button = QPushButton(tr("settings"))
        self.settings_button.clicked.connect(self.settings_dialog)
        control_layout.addWidget(self.settings_button)
        
        self.columns_button = QPushButton(tr("columns"))
        self.columns_button.clicked.connect(self.column_selection_dialog)
        control_layout.addWidget(self.columns_button)
        
        self.exit_button = QPushButton(tr("exit"))
        self.exit_button.clicked.connect(self.real_close)
        control_layout.addWidget(self.exit_button)
        
        main_layout.addLayout(control_layout)
        
        # Status bar
        self.status_bar = self.statusBar()
        self.update_label = QLabel(tr("last_update_never"))
        self.status_bar.addPermanentWidget(self.update_label)
        
        # Create menu
        self.create_menus()
        
        # Настраиваем колонки
        self.rebuild_tree_columns()
    
    def show_header_context_menu(self, pos):
        header = self.tree.header()
        logical_index = header.logicalIndexAt(pos)
        visible_columns = config_manager.visible_columns
        
        if logical_index < 0 or logical_index >= len(visible_columns):
            return
            
        col_id = visible_columns[logical_index]
        col_name = self.column_definitions.get(col_id, {}).get('name', col_id)
        
        menu = QMenu(self)
        
        # Действие для удаления колонки
        remove_action = QAction(tr("remove_column"), self)
        remove_action.triggered.connect(lambda: self.remove_column(logical_index))
        menu.addAction(remove_action)
        
        menu.exec_(header.mapToGlobal(pos))
    
    def remove_column(self, column_index):
        visible_columns = config_manager.visible_columns.copy()
        
        if column_index < len(visible_columns):
            col_id = visible_columns[column_index]
            
            # Удаляем колонку из видимых
            visible_columns.pop(column_index)
            config_manager.visible_columns = visible_columns
            config_manager.save_config()
            
            logger.info(f"Removed column: {col_id}")
            self.rebuild_tree_columns()
    
    def handle_column_resized(self, logical_index, old_size, new_size):
        """Обработчик ручного изменения ширины колонки"""
        visible_columns = config_manager.visible_columns
        if logical_index < len(visible_columns):
            col_id = visible_columns[logical_index]
            config_manager.set_column_width(col_id, new_size)
            self.manual_column_resize = True
            self.column_resize_timer.start(2000)  # Сбрасываем флаг через 2 секунды
            logger.debug(f"Column {col_id} resized to {new_size}")

    def handle_column_resize_timeout(self):
        """Сбрасываем флаг ручного изменения"""
        self.manual_column_resize = False
        logger.debug("Manual resize flag reset")

    def setup_signals(self):
        self.async_updater.server_updated.connect(self.handle_server_update)
        self.async_updater.update_started.connect(self.update_started)
        self.async_updater.update_completed.connect(self.update_completed)
        
        self.update_timer.timeout.connect(self.force_update)
        self.update_timer.setInterval(self.update_interval * 1000)
        self.update_timer.start()
    
    def rebuild_tree_columns(self):
        """Перестраиваем колонки без сброса данных"""
        logger.info("Rebuilding tree columns")
        self.save_column_widths()
        
        # Получаем текущие данные
        current_data = {}
        for srv, item in self.server_items.items():
            current_data[srv] = [item.text(i) for i in range(self.tree.columnCount())]
        
        # Настраиваем новые колонки
        visible_columns = config_manager.visible_columns
        self.tree.setColumnCount(len(visible_columns))
        
        headers = []
        for col_id in visible_columns:
            if col_id in self.column_definitions:
                headers.append(self.column_definitions[col_id]['name'])
            else:
                headers.append(col_id)
        
        self.tree.setHeaderLabels(headers)
        
        # Восстанавливаем данные в новых колонках
        for srv, item in self.server_items.items():
            for i, col_id in enumerate(visible_columns):
                if col_id in self.column_definitions:
                    # Используем актуальные данные вместо старых
                    try:
                        getter = self.column_definitions[col_id]['getter']
                        value = getter(srv)
                        item.setText(i, str(value))
                        # Устанавливаем тултип с полным текстом
                        item.setToolTip(i, str(value))
                    except Exception as e:
                        logger.error(f"Error updating column {col_id} for {srv}: {e}")
                        item.setText(i, "N/A")
                        item.setToolTip(i, "N/A")
                else:
                    # Для неизвестных колонок пытаемся восстановить старые данные
                    if i < len(current_data.get(srv, [])):
                        item.setText(i, current_data[srv][i])
        
        # Восстанавливаем ширину колонок
        self.adjust_column_widths()
    
    def adjust_column_widths(self):
        """Автоматически подгоняет ширину колонок с учетом ручных настроек"""
        if not self.tree.columnCount() or self.manual_column_resize:
            return
            
        # Рассчитываем доступную ширину
        available_width = self.tree.viewport().width()
        
        # 1. Применяем сохраненные ширины колонок
        visible_columns = config_manager.visible_columns
        total_saved_width = 0
        visible_count = 0
        
        for i, col_id in enumerate(visible_columns):
            if col_id in self.column_definitions:
                # Пробуем получить сохраненную ширину
                saved_width = config_manager.column_widths.get(col_id, None)
                
                # Если нет сохраненной, используем ширину по умолчанию
                if saved_width is None:
                    saved_width = self.column_definitions[col_id].get('default_width', 100)
                
                min_width = self.column_definitions[col_id]['min_width']
                
                # Проверяем минимальную ширину
                if saved_width < min_width:
                    saved_width = min_width
                
                self.tree.setColumnWidth(i, saved_width)
                total_saved_width += saved_width
                visible_count += 1
        
        # 2. Если есть колонки без сохраненной ширины
        remaining_columns = len(visible_columns) - visible_count
        if remaining_columns > 0:
            # Распределяем оставшееся пространство равномерно
            remaining_width = available_width - total_saved_width
            
            if remaining_width > 0:
                column_width = remaining_width // remaining_columns
                
                for i, col_id in enumerate(visible_columns):
                    if col_id in self.column_definitions and col_id not in config_manager.column_widths:
                        min_width = self.column_definitions[col_id]['min_width']
                        width = max(column_width, min_width)
                        self.tree.setColumnWidth(i, width)
                        total_saved_width += width
        
        # 3. Корректируем общую ширину, если есть расхождения
        if total_saved_width != available_width:
            width_difference = available_width - total_saved_width
            
            if width_difference != 0:
                # Распределяем разницу пропорционально
                for i, col_id in enumerate(visible_columns):
                    if col_id in self.column_definitions:
                        current_width = self.tree.columnWidth(i)
                        proportion = current_width / total_saved_width if total_saved_width > 0 else 1 / len(visible_columns)
                        adjustment = int(width_difference * proportion)
                        new_width = max(current_width + adjustment, self.column_definitions[col_id]['min_width'])
                        self.tree.setColumnWidth(i, new_width)
    
    def save_column_widths(self):
        """Сохраняет текущие ширины колонок в конфиг"""
        visible_columns = config_manager.visible_columns
        for i, col_id in enumerate(visible_columns):
            if col_id in self.column_definitions:
                width = self.tree.columnWidth(i)
                config_manager.set_column_width(col_id, width)
    
    def create_menus(self):
        menu_bar = self.menuBar()
        
        # Language menu
        language_menu = menu_bar.addMenu(tr("language"))
        
        # Динамически создаем пункты меню для каждого языка
        for lang_code, lang_name in localization.languages.items():
            action = QAction(lang_name, self)
            action.triggered.connect(lambda checked, lc=lang_code: self.change_language(lc))
            language_menu.addAction(action)
    
    def setup_tray_icon(self):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = QSystemTrayIcon(self)
            self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
            
            tray_menu = QMenu()
            show_action = QAction(tr("show"), self)
            show_action.triggered.connect(self.show_normal)
            tray_menu.addAction(show_action)
            
            exit_action = QAction(tr("exit"), self)
            exit_action.triggered.connect(self.real_close)
            tray_menu.addAction(exit_action)
            
            self.tray_icon.setContextMenu(tray_menu)
            self.tray_icon.activated.connect(self.tray_icon_activated)
            self.tray_icon.show()
    
    def tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_normal()
    
    def show_normal(self):
        self.show()
        self.activateWindow()
        self.raise_()
        
    def initial_populate(self):
        """Инициализация серверов в правильном порядке"""
        # Очищаем дерево перед началом
        self.tree.clear()
        self.server_items.clear()
        
        # Временно отключаем сортировку для сохранения порядка
        self.tree.setSortingEnabled(False)
        
        # Добавляем сервера в том же порядке, что и в конфиге
        for srv in self.server_list:
            item = QTreeWidgetItem(self.tree)
            self.update_server_item(item, srv)
            self.server_items[srv] = item
        
        # Включаем сортировку обратно
        self.tree.setSortingEnabled(True)
    
    def update_server_item(self, item, server):
        """Обновляет элемент дерева с учетом видимых колонок"""
        visible_columns = config_manager.visible_columns
        
        for i, col_id in enumerate(visible_columns):
            if col_id in self.column_definitions:
                try:
                    getter = self.column_definitions[col_id]['getter']
                    value = getter(server)
                    item.setText(i, str(value))
                    # Устанавливаем тултип с полным текстом
                    item.setToolTip(i, str(value))
                except Exception as e:
                    logger.error(f"Error updating column {col_id} for {server}: {e}")
                    item.setText(i, "N/A")
                    item.setToolTip(i, "N/A")
    
    def handle_server_update(self, server, data):
        if server not in self.server_items:
            logger.warning(f"Received update for unknown server: {server}")
            return
            
        # Сохраняем полный объект информации о сервере
        if data['info']:
            self.server_info_objects[server] = data['info']
            
            # Собираем все атрибуты ServerInfo
            attributes = [attr for attr in dir(data['info']) 
                         if not attr.startswith('_') 
                         and not callable(getattr(data['info'], attr))]
            self.all_info_attributes.update(attributes)
            
            # Преобразуем данные в удобный формат для таблицы
            self.server_info_data[server] = {
                'server_name': data['info'].server_name,
                'player_count': data['info'].player_count,
                'max_players': data['info'].max_players,
                'map_name': data['info'].map_name,
                'app_id': data['info'].app_id,
                'version': data['info'].version,
                'ping': data['info'].ping,
                'vac_enabled': data['info'].vac_enabled,
                'server_os': getattr(data['info'], 'server_os', 'N/A'),
                'folder': getattr(data['info'], 'folder', 'N/A'),
                'steam_id': getattr(data['info'], 'steam_id', 'N/A'),
                'keywords': getattr(data['info'], 'keywords', 'N/A'),
                'port': getattr(data['info'], 'port', 'N/A'),
            }
        else:
            # Удаляем объект, если информация недоступна
            if server in self.server_info_objects:
                del self.server_info_objects[server]
            self.server_info_data[server] = {}
            logger.warning(f"No info data for server: {server}")
        
        self.players_data[server] = data['players']
        
        # Собираем все ключи правил
        if data['rules']:
            self.rules_data[server] = data['rules']
            self.all_rule_keys.update(data['rules'].keys())
        else:
            self.rules_data[server] = {}
            
        logger.debug(f"Updated data for {server}: rules={len(data['rules'])}")
        
        # Перестраиваем определения колонок при появлении новых атрибутов
        old_columns = set(self.column_definitions.keys())
        self.column_definitions = self.create_column_definitions()
        new_columns = set(self.column_definitions.keys())
        
        # Если появились новые колонки, перестраиваем дерево
        if new_columns - old_columns:
            logger.info(f"New columns detected, rebuilding tree columns")
            self.rebuild_tree_columns()
        else:
            # Иначе просто обновляем элемент
            if server in self.server_items:
                self.update_server_item(self.server_items[server], server)
    
    def update_started(self):
        # Отключаем кнопку обновления при начале обновления
        self.refresh_button.setEnabled(False)
        self.status_bar.showMessage(tr("updating_servers"))
        logger.info("Update started")
    
    def update_completed(self):
        # Устанавливаем дату последнего обновления при завершении
        self.last_update = datetime.now()
        self.update_status()
        
        # Включаем кнопку обновления
        self.refresh_button.setEnabled(True)
        self.status_bar.showMessage(tr("update_completed"))
        logger.info("Update completed")
    
    def update_status(self):
        if self.last_update:
            time_str = self.last_update.strftime("%d.%m.%Y %H:%M:%S")
            self.update_label.setText(tr("last_update").format(time=time_str))
        else:
            self.update_label.setText(tr("last_update_never"))
    
    def force_update(self):
        # Блокируем кнопку обновления при начале обновления
        self.refresh_button.setEnabled(False)
        logger.info("Forcing update of all servers")
        self.async_updater._update_task = asyncio.create_task(self.async_updater.update_all_servers())
    
    def show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
            
        self.selected_server = None
        for srv, srv_item in self.server_items.items():
            if srv_item == item:
                self.selected_server = srv
                break
                
        if not self.selected_server:
            return
            
        logger.debug(f"Context menu for server: {self.selected_server}")
        menu = QMenu(self)
        
        copy_action = QAction(tr("copy_ip"), self)
        copy_action.triggered.connect(self.copy_ip)
        menu.addAction(copy_action)
        
        connect_action = QAction(tr("connect"), self)
        connect_action.triggered.connect(self.connect_to_selected)
        menu.addAction(connect_action)
        
        delete_action = QAction(tr("delete_server"), self)
        delete_action.triggered.connect(self.delete_server)
        menu.addAction(delete_action)
        
        menu.addSeparator()
        
        commands_action = QAction(tr("commands"), self)
        commands_action.triggered.connect(lambda: self.show_data_window('rules'))
        menu.addAction(commands_action)
        
        players_action = QAction(tr("players"), self)
        players_action.triggered.connect(lambda: self.show_data_window('players'))
        menu.addAction(players_action)
        
        info_action = QAction(tr("extra_info"), self)
        info_action.triggered.connect(lambda: self.show_data_window('info'))
        menu.addAction(info_action)
        
        menu.exec_(self.tree.viewport().mapToGlobal(pos))
    
    def format_duration(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours:02}:{minutes:02}"
    
    def show_data_window(self, data_type):
        if not self.selected_server:
            return
            
        server_str = self.selected_server
        logger.debug(f"Showing {data_type} window for server: {server_str}")
        window = QDialog(self)
        window.setWindowTitle(f"{tr(data_type)} - {server_str}")
        window.setGeometry(200, 200, 800, 600)
        
        layout = QVBoxLayout()
        tree = QTreeWidget()
        layout.addWidget(tree)
        
        if data_type == 'rules':
            rules = self.rules_data.get(server_str, {})
            logger.debug(f"Displaying {len(rules)} rules for {server_str}")
            tree.setHeaderLabels([tr('key'), tr('value')])
            for key, value in rules.items():
                item = QTreeWidgetItem(tree)
                item.setText(0, key)
                item.setText(1, str(value))
        
        elif data_type == 'players':
            players = self.players_data.get(server_str, [])
            logger.debug(f"Displaying {len(players)} players for {server_str}")
            tree.setHeaderLabels([tr('name'), tr('score'), tr('duration')])
            for player in players:
                if isinstance(player, a2s.Player) and player.name:
                    item = QTreeWidgetItem(tree)
                    item.setText(0, player.name)
                    item.setText(1, str(player.score))
                    item.setText(2, self.format_duration(player.duration))
        
        elif data_type == 'info':
            # Показываем все атрибуты объекта a2s.ServerInfo
            tree.setHeaderLabels([tr('attribute'), tr('value')])
            
            if server_str in self.server_info_objects:
                info_obj = self.server_info_objects[server_str]
                
                # Получаем все атрибуты объекта
                attributes = [attr for attr in dir(info_obj) 
                             if not attr.startswith('_') 
                             and not callable(getattr(info_obj, attr))]
                
                for attr in attributes:
                    try:
                        value = getattr(info_obj, attr)
                        
                        # Специальная обработка для некоторых типов данных
                        if isinstance(value, bool):
                            value = tr("true") if value else tr("false")
                        elif isinstance(value, (list, tuple)):
                            value = ', '.join(map(str, value))
                        elif isinstance(value, bytes):
                            value = value.decode('utf-8', errors='ignore')
                        elif attr == 'ping':
                            value = f"{value*1000:.0f} ms"
                        
                        item = QTreeWidgetItem(tree)
                        item.setText(0, tr(attr) if tr(attr) != attr else attr)
                        item.setText(1, str(value))
                    except Exception as e:
                        logger.error(f"Error getting attribute {attr}: {e}")
            else:
                item = QTreeWidgetItem(tree)
                item.setText(0, tr("no_info_available"))
                item.setText(1, "")
        
        close_button = QPushButton(tr("close"))
        close_button.clicked.connect(window.close)
        layout.addWidget(close_button)
        
        window.setLayout(layout)
        window.exec_()
    
    def copy_ip(self):
        if self.selected_server:
            pyperclip.copy(self.selected_server)
            logger.debug(f"Copied IP to clipboard: {self.selected_server}")
    
    def connect_to_selected(self):
        if self.selected_server:
            server_str = self.selected_server
            version = self.server_info_data.get(server_str, {}).get('version', '')
            logger.info(f"Connecting to server: {server_str}")
            self.connect_to_server(server_str, version)
    
    def connect_to_server(self, server_str, version):
        try:
            address, port = server_str.split(':')
            ip_address = socket.gethostbyname(address)
            protocol = 'clientmod://' if is_css_v34(version) else 'steam://'
            connect_url = f"{protocol}connect/{ip_address}:{port}"
            webbrowser.open(connect_url)
            logger.info(f"Opened connection URL: {connect_url}")
        except Exception as e:
            logger.error(f"Connection error: {str(e)}")
            QMessageBox.critical(self, tr("error"), f"{tr('connection_error_msg')}:\n{str(e)}")
    
    def delete_server(self):
        if self.selected_server and self.selected_server in self.server_list:
            reply = QMessageBox.question(
                self,
                tr("confirmation"),
                tr("confirm_delete_server").format(server=self.selected_server),
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                logger.info(f"Deleting server: {self.selected_server}")
                # Удаляем сервер из списка
                self.server_list.remove(self.selected_server)
                config_manager.servers = self.server_list
                config_manager.save_config()
                
                # Удаляем элемент из дерева и словаря
                if self.selected_server in self.server_items:
                    item = self.server_items[self.selected_server]
                    index = self.tree.indexOfTopLevelItem(item)
                    if index >= 0:
                        self.tree.takeTopLevelItem(index)
                    del self.server_items[self.selected_server]
                
                # Удаляем данные сервера
                if self.selected_server in self.players_data:
                    del self.players_data[self.selected_server]
                if self.selected_server in self.server_info_data:
                    del self.server_info_data[self.selected_server]
                if self.selected_server in self.server_info_objects:
                    del self.server_info_objects[self.selected_server]
                if self.selected_server in self.rules_data:
                    del self.rules_data[self.selected_server]
                
                self.async_updater.server_list = self.server_list.copy()
    
    def add_server_dialog(self):
        server, ok = QInputDialog.getText(
            self,
            tr("add_server"),
            tr("enter_server_address")
        )
        
        if ok and server:
            server = server.strip()
            logger.debug(f"User entered server: {server}")
            if ':' not in server:
                QMessageBox.critical(self, tr("error"), tr("invalid_format"))
                return
                
            if server in self.server_list:
                QMessageBox.information(self, tr("info"), tr("server_exists"))
                return
                
            self.server_list.append(server)
            config_manager.servers = self.server_list
            config_manager.save_config()
            
            # Добавляем сервер с отключенной сортировкой
            self.tree.setSortingEnabled(False)
            item = QTreeWidgetItem(self.tree)
            self.update_server_item(item, server)
            self.server_items[server] = item
            self.tree.setSortingEnabled(True)
            
            self.async_updater.server_list = self.server_list.copy()
            
            # Обновляем данные для нового сервера
            self.force_update()
    
    def settings_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("settings"))
        layout = QVBoxLayout()
        
        # Update interval
        interval_layout = QHBoxLayout()
        interval_label = QLabel(tr("update_interval_sec"))
        interval_layout.addWidget(interval_label)
        
        interval_edit = QLineEdit(str(self.update_interval))
        interval_layout.addWidget(interval_edit)
        
        layout.addLayout(interval_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_button = QPushButton(tr("ok"))
        ok_button.clicked.connect(lambda: self.apply_settings(interval_edit.text(), dialog))
        button_layout.addWidget(ok_button)
        
        cancel_button = QPushButton(tr("cancel"))
        cancel_button.clicked.connect(dialog.close)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        dialog.setLayout(layout)
        dialog.exec_()
    
    def apply_settings(self, interval, dialog):
        try:
            new_interval = int(interval)
            if new_interval < 1:
                raise ValueError
                
            self.update_interval = new_interval
            config_manager.update_interval = new_interval
            config_manager.save_config()
            
            self.update_timer.stop()
            self.update_timer.setInterval(new_interval * 1000)
            self.update_timer.start()
            
            dialog.close()
            logger.info(f"Update interval changed to {new_interval} seconds")
        except ValueError:
            QMessageBox.critical(self, tr("error"), tr("invalid_number"))
    
    def column_selection_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("select_columns"))
        dialog.setMinimumSize(600, 500)
        
        layout = QVBoxLayout()
        splitter = QSplitter(Qt.Horizontal)
        
        # Список доступных колонок
        available_group = QGroupBox(tr("available_columns"))
        available_layout = QVBoxLayout()
        self.available_list = DraggableListWidget()
        self.available_list.setSelectionMode(QAbstractItemView.SingleSelection)
        
        # Поиск
        search_edit = QLineEdit()
        search_edit.setPlaceholderText(tr("search_columns"))
        search_edit.textChanged.connect(self.filter_columns)
        available_layout.addWidget(search_edit)
        available_layout.addWidget(self.available_list)
        available_group.setLayout(available_layout)
        
        # Список выбранных колонок
        selected_group = QGroupBox(tr("selected_columns"))
        selected_layout = QVBoxLayout()
        self.selected_list = DraggableListWidget()
        self.selected_list.setSelectionMode(QAbstractItemView.SingleSelection)
        selected_layout.addWidget(self.selected_list)
        selected_group.setLayout(selected_layout)
        
        splitter.addWidget(available_group)
        splitter.addWidget(selected_group)
        splitter.setSizes([300, 300])
        layout.addWidget(splitter)
        
        # Кнопки управления
        btn_layout = QHBoxLayout()
        add_btn = QPushButton(">>")
        add_btn.clicked.connect(self.add_selected_columns)
        btn_layout.addWidget(add_btn)
        
        remove_btn = QPushButton("<<")
        remove_btn.clicked.connect(self.remove_selected_columns)
        btn_layout.addWidget(remove_btn)
        
        up_btn = QPushButton("↑")
        up_btn.clicked.connect(self.move_column_up)
        btn_layout.addWidget(up_btn)
        
        down_btn = QPushButton("↓")
        down_btn.clicked.connect(self.move_column_down)
        btn_layout.addWidget(down_btn)
        
        layout.addLayout(btn_layout)
        
        # Заполняем списки
        self.populate_column_lists()
        
        # Кнопки диалога
        btn_box = QHBoxLayout()
        apply_btn = QPushButton(tr("apply"))
        apply_btn.clicked.connect(lambda: self.apply_column_selection(dialog))
        btn_box.addWidget(apply_btn)
        
        cancel_btn = QPushButton(tr("cancel"))
        cancel_btn.clicked.connect(dialog.close)
        btn_box.addWidget(cancel_btn)
        
        layout.addLayout(btn_box)
        dialog.setLayout(layout)
        dialog.exec_()
    
    def populate_column_lists(self):
        """Заполняет списки колонок"""
        self.available_list.clear()
        self.selected_list.clear()
        
        # Все возможные колонки
        all_columns = list(self.column_definitions.keys())
        visible_columns = config_manager.visible_columns
        
        # Добавляем выбранные колонки
        for col_id in visible_columns:
            if col_id in self.column_definitions:
                name = self.column_definitions[col_id]['name']
                item = QListWidgetItem(f"{name}")
                item.setData(Qt.UserRole, col_id)
                self.selected_list.addItem(item)
        
        # Добавляем доступные колонки
        for col_id in all_columns:
            if col_id not in visible_columns:
                name = self.column_definitions[col_id]['name']
                item = QListWidgetItem(f"{name}")
                item.setData(Qt.UserRole, col_id)
                self.available_list.addItem(item)
    
    def filter_columns(self, text):
        """Фильтрует список доступных колонок"""
        text = text.lower()
        for i in range(self.available_list.count()):
            item = self.available_list.item(i)
            item_text = item.text().lower()
            item.setHidden(text not in item_text)
    
    def add_selected_columns(self):
        """Добавляет выбранные колонки в список выбранных"""
        selected_items = self.available_list.selectedItems()
        for item in selected_items:
            col_id = item.data(Qt.UserRole)
            
            # Проверяем, не добавлена ли уже колонка
            for i in range(self.selected_list.count()):
                if self.selected_list.item(i).data(Qt.UserRole) == col_id:
                    continue
            
            # Переносим в выбранные
            new_item = QListWidgetItem(item.text())
            new_item.setData(Qt.UserRole, col_id)
            self.selected_list.addItem(new_item)
            
            # Удаляем из доступных
            self.available_list.takeItem(self.available_list.row(item))
    
    def remove_selected_columns(self):
        """Удаляет выбранные колонки из списка выбранных"""
        selected_items = self.selected_list.selectedItems()
        for item in selected_items:
            col_id = item.data(Qt.UserRole)
            
            # Проверяем, не добавлена ли уже колонка
            for i in range(self.available_list.count()):
                if self.available_list.item(i).data(Qt.UserRole) == col_id:
                    continue
            
            # Переносим в доступные
            new_item = QListWidgetItem(item.text())
            new_item.setData(Qt.UserRole, col_id)
            self.available_list.addItem(new_item)
            
            # Удаляем из выбранных
            self.selected_list.takeItem(self.selected_list.row(item))
    
    def move_column_up(self):
        """Перемещает выбранную колонку вверх"""
        selected_items = self.selected_list.selectedItems()
        if not selected_items:
            return
            
        row = self.selected_list.row(selected_items[0])
        if row > 0:
            item = self.selected_list.takeItem(row)
            self.selected_list.insertItem(row - 1, item)
            self.selected_list.setCurrentRow(row - 1)
    
    def move_column_down(self):
        """Перемещает выбранную колонку вниз"""
        selected_items = self.selected_list.selectedItems()
        if not selected_items:
            return
            
        row = self.selected_list.row(selected_items[0])
        if row < self.selected_list.count() - 1:
            item = self.selected_list.takeItem(row)
            self.selected_list.insertItem(row + 1, item)
            self.selected_list.setCurrentRow(row + 1)
    
    def apply_column_selection(self, dialog):
        """Применяет выбранные колонки"""
        selected_columns = []
        for i in range(self.selected_list.count()):
            item = self.selected_list.item(i)
            col_id = item.data(Qt.UserRole)
            selected_columns.append(col_id)
        
        if not selected_columns:
            QMessageBox.warning(self, tr("warning"), tr("select_at_least_one_column"))
            return
        
        # Обновляем видимые колонки
        config_manager.visible_columns = selected_columns
        config_manager.save_config()
        logger.info(f"Updated visible columns: {selected_columns}")
        
        # Полностью перестраиваем колонки
        self.rebuild_tree_columns()
        
        dialog.close()
    
    def change_language(self, lang_code):
        config_manager.language = lang_code
        config_manager.save_config()
        localization.load_language(lang_code)
        
        # Обновляем весь интерфейс
        self.setWindowTitle(tr("server_monitor"))
        self.add_button.setText(tr("add_server"))
        self.refresh_button.setText(tr("refresh_now"))
        self.settings_button.setText(tr("settings"))
        self.columns_button.setText(tr("columns"))
        self.exit_button.setText(tr("exit"))
        
        # Обновляем определения колонок
        self.column_definitions = self.create_column_definitions()
        
        # Перестраиваем колонки
        self.rebuild_tree_columns()
    
    def real_close(self):
        """Реальный выход из приложения"""
        self.real_exit = True
        
        # Сохраняем геометрию окна
        config_manager.window_geometry = self.saveGeometry()
        
        # Сохраняем ширину колонок
        self.save_column_widths()
        
        config_manager.save_config()
        
        self.close()
    
    def closeEvent(self, event):
        if self.real_exit:
            # Отменяем все асинхронные задачи
            self.async_updater.cancel_updates()
            self.update_timer.stop()
            
            # Удаляем иконку из трея
            if self.tray_icon:
                self.tray_icon.hide()
                self.tray_icon.deleteLater()
                self.tray_icon = None
            
            # Завершаем приложение
            QCoreApplication.instance().quit()
            event.accept()
        else:
            if self.tray_icon and self.tray_icon.isVisible():
                self.hide()
                event.ignore()
    
    def resizeEvent(self, event):
        """Обработчик изменения размера окна"""
        super().resizeEvent(event)
        # При изменении размера окна пересчитываем ширину колонок
        if not self.manual_column_resize:
            self.adjust_column_widths()

def main():
    # Создаем приложение Qt
    app = QApplication(sys.argv)
    
    # Создаем и настраиваем event loop
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    
    # Загружаем конфиг и локализацию
    config_manager.load_config()
    localization.load_language(config_manager.language)
    
    # Создаем главное окно
    window = ServerMonitorApp()
    window.show()
    
    # Запускаем первоначальное обновление
    asyncio.get_event_loop().create_task(window.async_updater.update_all_servers())
    
    # Запускаем приложение
    with loop:
        loop.run_forever()

if __name__ == "__main__":
    main()
