import a2s
import tkinter as tk
from tkinter import ttk, messagebox
import asyncio
import webbrowser
from datetime import datetime
import socket
import pyperclip
import json
from pathlib import Path
from collections import OrderedDict

LOCALE_DIR = Path(__file__).parent / 'locales'
CONFIG_FILE = Path(__file__).parent / 'config.json'
DEFAULT_LANGUAGE = 'ru_RU'
DEFAULT_UPDATE_INTERVAL = 30
DEFAULT_SERVERS = [
    'pug1.war-lords.net:27020',
    'pug2.war-lords.net:27021',
    'pug3.war-lords.net:27022',
    'pug1eu.war-lords.net:27016',
    '193.31.28.17:27015',
    '193.31.28.17:27035',
    '31.58.91.239:27015'
]

class AsyncTk(tk.Tk):
    def __init__(self):
        super().__init__()
        self.running = True
        self.protocol("WM_DELETE_WINDOW", self.close)

    async def async_loop(self):
        while self.running:
            self.update()
            await asyncio.sleep(0.05)
    
    def close(self):
        self.running = False
        self.destroy()

class ConfigManager:
    def __init__(self):
        self.config = {
            'language': DEFAULT_LANGUAGE,
            'update_interval': DEFAULT_UPDATE_INTERVAL,
            'servers': DEFAULT_SERVERS.copy()
        }
        self.load_config()

    def load_config(self):
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, 'r') as f:
                    loaded_config = json.load(f)
                    self.config.update({
                        'language': loaded_config.get('language', DEFAULT_LANGUAGE),
                        'update_interval': loaded_config.get('update_interval', DEFAULT_UPDATE_INTERVAL),
                        'servers': loaded_config.get('servers', DEFAULT_SERVERS.copy())
                    })
        except Exception as e:
            print(f"Config load error: {e}")
            self.save_config()

    def save_config(self):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Config save error: {e}")

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

class Localization:
    def __init__(self, config):
        self.config = config
        self.strings = self.load_language(self.config.language)

    def load_language(self, lang_code):
        try:
            with open(LOCALE_DIR / f'{lang_code}.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Language load error: {e}")
            return {}

config_manager = ConfigManager()
localization = Localization(config_manager)

def tr(key):
    return localization.strings.get(key, key)

def is_css_v34(version):
    return str(version) == '1.0.0.34'

class ServerMonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title(tr("server_monitor"))
        self.server_list = config_manager.servers.copy()
        self.update_interval = config_manager.update_interval
        self.last_update = None
        self.selected_server_data = None
        self.server_items = {}
        self.update_task = None
        self.players_data = {}
        self.server_info_data = {}
        self.rules_data = {}
        
        self.setup_ui()
        self.initial_populate()
        self.setup_keybindings()

    def setup_ui(self):
        self.menu_bar = tk.Menu(self.root)
        self.language_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.language_menu.add_command(label="English", command=lambda: self.change_language('en_US'))
        self.language_menu.add_command(label="Русский", command=lambda: self.change_language('ru_RU'))
        self.menu_bar.add_cascade(label=tr("language"), menu=self.language_menu)
        self.root.config(menu=self.menu_bar)

        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        columns = [
            ('Server', tr("server"), 150),
            ('Online', tr("online"), 80),
            ('IP:Port', tr("ip_port"), 120),
            ('Map', tr("map"), 120),
            ('Platform', tr("platform"), 150),
            ('Ping', tr("ping"), 60)
        ]
        
        self.tree = ttk.Treeview(main_frame, columns=[col[0] for col in columns], show='headings')
        for col_id, text, width in columns:
            self.tree.heading(col_id, text=text)
            self.tree.column(col_id, width=width, anchor='center')

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label=tr("copy_ip"), command=self.copy_ip)
        self.context_menu.add_command(label=tr("connect"), command=self.connect_to_selected)
        self.context_menu.add_command(label=tr("delete_server"), command=self.delete_server)
        self.context_menu.add_separator()
        self.context_menu.add_command(label=tr("commands"), command=lambda: asyncio.create_task(self.show_rules()))
        self.context_menu.add_command(label=tr("players"), command=lambda: asyncio.create_task(self.show_players()))
        self.context_menu.add_command(label=tr("extra_info"), command=lambda: asyncio.create_task(self.show_extra_info()))
        
        self.tree.bind("<Button-3>", self.show_context_menu)
        self.tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        control_frame = ttk.Frame(main_frame, padding=5)
        control_frame.pack(side=tk.RIGHT, fill=tk.Y)

        buttons = [
            (tr("add_server"), self.add_server_dialog),
            (tr("refresh_now"), self.force_update),
            (tr("settings"), self.settings_dialog),
            (tr("exit"), self.root.close)
        ]
        
        for text, command in buttons:
            ttk.Button(control_frame, text=text, command=command).pack(pady=5, fill=tk.X)

        self.status_bar = ttk.Frame(self.root)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.update_label = ttk.Label(self.status_bar, text=tr("last_update_never"), anchor='e')
        self.update_label.pack(side=tk.RIGHT, padx=5)

    def initial_populate(self):
        self.tree.delete(*self.tree.get_children())
        self.server_items.clear()
        for srv in self.server_list:
            item_id = self.tree.insert('', 'end', values=(
                tr("loading"),
                '...',
                srv,
                '...',
                '...',
                '...'
            ))
            self.server_items[srv] = item_id
        self.force_update()

    async def fetch_all_data(self, server):
        try:
            address, port = server.split(':')
            address_tuple = (address, int(port))
            
            info, players, rules = await asyncio.gather(
                a2s.ainfo(address_tuple, timeout=3),
                a2s.aplayers(address_tuple, timeout=5),
                a2s.arules(address_tuple, timeout=3)
            )
            
            return {
                'server': server,
                'base_info': {
                    'server': info.server_name,
                    'online': f"{info.player_count}/{info.max_players}",
                    'map': info.map_name,
                    'platform': f"{info.app_id}, {info.version}",
                    'ping': f"{info.ping*1000:.0f} ms"
                },
                'players': players,
                'rules': rules,
                'full_info': info
            }
        except Exception as e:
            print(f"Error fetching data for {server}: {e}")
            return {
                'server': server,
                'base_info': {
                    'server': tr("connection_error"),
                    'online': 'N/A',
                    'map': 'N/A',
                    'platform': 'N/A',
                    'ping': 'N/A'
                },
                'players': [],
                'rules': {},
                'full_info': None
            }

    async def update_servers(self):
        self.last_update = datetime.now()
        self.update_status()
        
        self.players_data.clear()
        self.rules_data.clear()
        self.server_info_data.clear()
        
        tasks = [asyncio.create_task(self.fetch_all_data(srv)) for srv in self.server_list]
        
        for task in asyncio.as_completed(tasks):
            data = await task
            srv = data['server']
            if srv in self.server_items:
                self.root.after(0, self.update_server_row, srv, data['base_info'])
                self.players_data[srv] = data['players']
                self.rules_data[srv] = data['rules']
                self.server_info_data[srv] = data['full_info']

        self.schedule_next_update()

    def update_server_row(self, srv, result):
        item_id = self.server_items[srv]
        self.tree.item(item_id, values=(
            result['server'],
            result['online'],
            srv,
            result['map'],
            result['platform'],
            result['ping']
        ))

    def schedule_next_update(self):
        if self.update_task and not self.update_task.done():
            self.update_task.cancel()
        self.update_task = asyncio.create_task(self.delayed_update())

    async def delayed_update(self):
        await asyncio.sleep(self.update_interval)
        await self.update_servers()

    def force_update(self):
        if self.update_task and not self.update_task.done():
            self.update_task.cancel()
        asyncio.create_task(self.update_servers())

    def create_data_window(self, title, columns, data):
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry("800x600")
        
        frame = ttk.Frame(window)
        frame.pack(fill=tk.BOTH, expand=True)
        
        tree = ttk.Treeview(frame, columns=columns, show='headings')
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=150, anchor='w')
        
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        for item in data:
            tree.insert('', 'end', values=item)
        
        ttk.Button(window, text=tr("close"), command=window.destroy).pack(pady=5)

    def format_duration(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours:02}:{minutes:02}"

    async def show_rules(self):
        if not self.selected_server_data:
            return
        
        server_str = self.selected_server_data[2]
        rules = self.rules_data.get(server_str, {})
        
        sorted_rules = OrderedDict(sorted(rules.items()))
        data = [(k, str(v)) for k, v in sorted_rules.items()]
        self.root.after(0, self.create_data_window, 
                      f"{tr('rules_for')} {server_str}", 
                      [tr('key'), tr('value')], 
                      data)

    async def show_players(self):
        if not self.selected_server_data:
            return
        
        server_str = self.selected_server_data[2]
        players = self.players_data.get(server_str, [])
        
        data = []
        for player in players:
            if isinstance(player, a2s.Player) and player.name:
                duration = self.format_duration(player.duration)
                data.append((player.name, str(player.score), duration))
        
        self.root.after(0, self.create_data_window,
                      f"{tr('players_on')} {server_str}",
                      [tr('name'), tr('score'), tr('duration')],
                      data)

    async def show_extra_info(self):
        if not self.selected_server_data:
            return
        
        server_str = self.selected_server_data[2]
        info = self.server_info_data.get(server_str)
        if not info:
            return
        
        exclude_fields = {'server_name', 'player_count', 'max_players', 
                         'map_name', 'app_id', 'version', 'ping'}
        extra_info = []
        
        for field in dir(info):
            if not field.startswith('_') and field not in exclude_fields:
                value = getattr(info, field)
                if value is not None:
                    extra_info.append((tr(field), str(value)))
        
        self.root.after(0, self.create_data_window,
                      f"{tr('extra_info_for')} {server_str}",
                      [tr('parameter'), tr('value')],
                      sorted(extra_info))

    def setup_keybindings(self):
        self.root.bind_all("<Control-a>", self.select_all)
        self.root.bind_all("<Control-c>", self.copy_text)
        self.root.bind_all("<Control-v>", self.paste_text)

    def select_all(self, event):
        widget = self.root.focus_get()
        if isinstance(widget, (ttk.Entry, tk.Text)):
            widget.tag_add('sel', '1.0', 'end')
            return "break"

    def copy_text(self, event):
        widget = self.root.focus_get()
        if isinstance(widget, (ttk.Entry, tk.Text)):
            widget.event_generate("<<Copy>>")
            return "break"

    def paste_text(self, event):
        widget = self.root.focus_get()
        if isinstance(widget, (ttk.Entry, tk.Text)):
            widget.event_generate("<<Paste>>")
            return "break"

    def change_language(self, lang_code):
        config_manager.language = lang_code
        config_manager.save_config()
        localization.strings = localization.load_language(lang_code)
        self.reload_ui()

    def reload_ui(self):
        for widget in self.root.winfo_children():
            widget.destroy()
        self.setup_ui()
        self.initial_populate()

    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.selected_server_data = self.tree.item(item)['values']
            self.context_menu.post(event.x_root, event.y_root)

    def copy_ip(self):
        if self.selected_server_data:
            pyperclip.copy(self.selected_server_data[2])

    def connect_to_selected(self):
        if self.selected_server_data:
            ip_port = self.selected_server_data[2]
            version = self.selected_server_data[4].split(', ')[-1] if self.selected_server_data[4] != 'N/A' else ''
            self.connect_to_server(ip_port, version)

    def connect_to_server(self, server_str, version):
        try:
            address, port = server_str.split(':')
            ip_address = socket.gethostbyname(address)
            protocol = 'clientmod://' if is_css_v34(version) else 'steam://'
            connect_url = f"{protocol}connect/{ip_address}:{port}"
            webbrowser.open(connect_url)
        except Exception as e:
            messagebox.showerror(tr("error"), f"{tr('connection_error')}:\n{str(e)}")

    def delete_server(self):
        if self.selected_server_data:
            server = self.selected_server_data[2]
            if server in self.server_list:
                self.server_list.remove(server)
                self.save_servers()
                self.initial_populate()

    def add_server_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title(tr("add_server"))
        
        ttk.Label(dialog, text=tr("enter_server_address")).pack(padx=10, pady=5)
        entry = ttk.Entry(dialog, width=30)
        entry.pack(padx=10, pady=5)
        
        entry.bind("<Control-a>", self.select_all)
        entry.bind("<Control-c>", self.copy_text)
        entry.bind("<Control-v>", self.paste_text)
        
        ttk.Button(dialog, text=tr("ok"), command=lambda: self.process_server_input(entry.get().strip(), dialog)).pack(pady=5)
        ttk.Button(dialog, text=tr("cancel"), command=dialog.destroy).pack(pady=5)

    def process_server_input(self, server, dialog):
        dialog.destroy()
        if not server:
            return
            
        if ':' not in server:
            messagebox.showerror(tr("error"), tr("invalid_format"))
            return
            
        if server in self.server_list:
            messagebox.showinfo(tr("info"), tr("server_exists"))
            return
            
        self.server_list.append(server)
        self.save_servers()
        self.initial_populate()

    def update_status(self):
        if self.last_update:
            time_str = self.last_update.strftime("%d.%m.%Y %H:%M:%S")
            self.update_label.config(text=tr("last_update").format(time=time_str))
        else:
            self.update_label.config(text=tr("last_update_never"))

    def save_servers(self):
        config_manager.servers = self.server_list.copy()
        config_manager.save_config()

    def settings_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title(tr("settings"))
        
        ttk.Label(dialog, text=tr("update_interval_sec")).pack(padx=10, pady=5)
        entry = ttk.Entry(dialog)
        entry.insert(0, str(self.update_interval))
        entry.pack(padx=10, pady=5)
        
        entry.bind("<Control-a>", self.select_all)
        entry.bind("<Control-c>", self.copy_text)
        entry.bind("<Control-v>", self.paste_text)
        
        ttk.Button(dialog, text=tr("ok"), command=lambda: self.process_settings(entry.get(), dialog)).pack(pady=5)
        ttk.Button(dialog, text=tr("cancel"), command=dialog.destroy).pack(pady=5)

    def process_settings(self, value, dialog):
        try:
            new_interval = int(value)
            if new_interval < 1:
                raise ValueError
            self.update_interval = new_interval
            config_manager.update_interval = new_interval
            config_manager.save_config()
            self.schedule_next_update()
            dialog.destroy()
        except ValueError:
            messagebox.showerror(tr("error"), tr("invalid_number"))

async def main():
    root = AsyncTk()
    app = ServerMonitorApp(root)
    await root.async_loop()

if __name__ == "__main__":
    asyncio.run(main())
