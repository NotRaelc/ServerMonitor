import a2s
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import os
import threading
from queue import Queue
import webbrowser
from datetime import datetime
import socket
import pyperclip  # Для работы с буфером обмена

def get_platform(version):
    version = str(version)
    platform_map = {
        '9540945': 'CSS v93',
        '6630498': 'CSS V92',
        '1.38.8.1': 'CS:GO',
        '1.0.0.34': 'CSS v34',
        '1.35.3.102': 'Classic Counter'
    }
    return platform_map.get(version, version)

class ServerMonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Server Monitor")
        self.server_list = []
        self.update_interval = 30
        self.queue = Queue()
        self.last_update = None
        self.selected_server = None
        
        self.setup_ui()
        self.load_servers()
        self.update_data()
        self.process_queue()

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(main_frame, 
                               columns=('Server', 'Online', 'IP:Port', 'Map', 'Platform', 'Ping'), 
                               show='headings')
        
        columns = {
            'Server': ('Сервер', 150),
            'Online': ('Онлайн', 80),
            'IP:Port': ('IP:Порт', 120),
            'Map': ('Карта', 120),
            'Platform': ('Платформа', 120),
            'Ping': ('Пинг', 60)
        }
        
        for col, (text, width) in columns.items():
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor='center')

        # Контекстное меню
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Копировать IP", command=self.copy_ip)
        self.context_menu.add_command(label="Присоединиться", command=self.connect_to_selected)
        self.context_menu.add_command(label="Удалить сервер", command=self.delete_server)

        self.tree.bind("<Button-3>", self.show_context_menu)
        self.tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        control_frame = ttk.Frame(main_frame, padding=5)
        control_frame.pack(side=tk.RIGHT, fill=tk.Y)

        buttons = [
            ("Добавить сервер", self.add_server_dialog),
            ("Обновить сейчас", self.update_data),
            ("Настройки", self.settings_dialog),
            ("Выход", self.root.quit)
        ]
        
        for text, command in buttons:
            ttk.Button(control_frame, text=text, command=command).pack(pady=5, fill=tk.X)

        self.status_bar = ttk.Frame(self.root)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.update_label = ttk.Label(
            self.status_bar, 
            text="Последнее обновление: еще не было",
            anchor='e'
        )
        self.update_label.pack(side=tk.RIGHT, padx=5)

    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.selected_server = self.tree.item(item)['values'][2]
            self.context_menu.post(event.x_root, event.y_root)

    def copy_ip(self):
        if self.selected_server:
            pyperclip.copy(self.selected_server)

    def connect_to_selected(self):
        if self.selected_server:
            self.connect_to_server(self.selected_server)

    def delete_server(self):
        if self.selected_server and self.selected_server in self.server_list:
            self.server_list.remove(self.selected_server)
            self.save_servers()
            self.update_data()

    def add_server_dialog(self):
        self.root.clipboard_clear()
        try:
            clipboard_content = self.root.clipboard_get()
        except tk.TclError:
            clipboard_content = ""
        
        server = simpledialog.askstring(
            "Добавить сервер",
            "Введите адрес сервера (host:port):",
            initialvalue=clipboard_content
        )
        self.process_server_input(server)

    def process_server_input(self, server):
        if server:
            if ':' not in server:
                messagebox.showerror("Ошибка", "Неправильный формат! Используйте host:port")
                return
            if server not in self.server_list:
                self.server_list.append(server)
                self.save_servers()
                self.update_data()
            else:
                messagebox.showinfo("Информация", "Сервер уже существует в списке")

    def update_status(self):
        if self.last_update:
            time_str = self.last_update.strftime("%d.%m.%Y %H:%M:%S")
            self.update_label.config(text=f"Последнее обновление: {time_str}")
        else:
            self.update_label.config(text="Последнее обновление: еще не было")

    def connect_to_server(self, server_str):
        try:
            address, port = server_str.split(':')
            ip_address = socket.gethostbyname(address)
            connect_url = f"steam://connect/{ip_address}:{port}"
            webbrowser.open(connect_url)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка подключения:\n{str(e)}")

    def load_servers(self):
        filename = 'servers.txt'
        if not os.path.exists(filename):
            default_servers = [
                'pug1.war-lords.net:27020',
                'pug2.war-lords.net:27021',
                'pug3.war-lords.net:27022',
                'pug1eu.war-lords.net:27016',
                '193.31.28.17:27015',
                '193.31.28.17:27035',
                '31.58.91.239:27015'
            ]
            with open(filename, 'w') as f:
                f.write('\n'.join(default_servers))
        
        with open(filename, 'r') as f:
            self.server_list = [line.strip() for line in f if line.strip()]

    def save_servers(self):
        with open('servers.txt', 'w') as f:
            f.write('\n'.join(self.server_list))

    def fetch_data(self, server):
        try:
            address, port = server.split(':')
            info = a2s.info((address, int(port)), timeout=3)
            return [
                info.server_name,
                f"{info.player_count}/{info.max_players}",
                server,
                info.map_name,
                get_platform(info.version),
                f"{info.ping*1000:.0f} ms"
            ]
        except Exception as e:
            return ["Ошибка подключения", 'N/A', server, 'N/A', 'N/A', 'N/A']

    def update_data(self):
        def worker():
            results = [self.fetch_data(srv) for srv in self.server_list]
            self.queue.put(lambda: self.update_treeview(results))
            self.root.after(self.update_interval * 1000, self.update_data)
        
        threading.Thread(target=worker, daemon=True).start()

    def update_treeview(self, data):
        self.tree.delete(*self.tree.get_children())
        for item in data:
            self.tree.insert('', 'end', values=item)
        self.last_update = datetime.now()
        self.update_status()

    def process_queue(self):
        while not self.queue.empty():
            self.queue.get()()
        self.root.after(100, self.process_queue)

    def settings_dialog(self):
        new_interval = simpledialog.askinteger("Настройки", 
                                             "Интервал обновления (секунды):",
                                             initialvalue=self.update_interval)
        if new_interval and new_interval > 0:
            self.update_interval = new_interval

if __name__ == "__main__":
    root = tk.Tk()
    app = ServerMonitorApp(root)
    root.mainloop()