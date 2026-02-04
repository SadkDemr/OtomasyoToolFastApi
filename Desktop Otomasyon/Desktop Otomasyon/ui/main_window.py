import customtkinter as ctk
import threading
import logging
from tkinter import filedialog, messagebox

from core.scenario import Scenario, Action
from core.runner import AutomationRunner
from drivers.desktop_driver import DesktopDriver
from ui.snip_tool import SnipTool
from ui.recorder import Recorder
from core.database import DatabaseManager
import json
import os
import datetime

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        from core.config import APP_VERSION
        self.title(f"Desktop Otomasyon - {APP_VERSION}")
        self.geometry("1000x700")

        # Core Components
        self.driver = DesktopDriver()
        self.runner = AutomationRunner(self.driver)
        self.db = DatabaseManager()
        self.recorder = None
        self.drag_index = None # For Drag & Drop
        self.current_scenario = Scenario(name="Yeni Senaryo", description="")

        # Layout Setup
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._setup_left_panel()
        self._setup_main_panel()
        self._setup_right_panel()
        
        # Log Handler to redirect logs to UI
        # Log Handler to redirect logs to UI
        self._setup_logging()
        
        # Recorder instance
        # self.recorder = None # Moved up


    def _setup_left_panel(self):
        """Aksiyon Ekleme Paneli"""
        self.left_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.left_frame.grid(row=0, column=0, sticky="nswe")
        
        self.lbl_toolbox = ctk.CTkLabel(self.left_frame, text="Aksiyonlar", font=("Arial", 16, "bold"))
        self.lbl_toolbox.pack(pady=10, padx=10)

        # Smart Actions
        self.lbl_smart = ctk.CTkLabel(self.left_frame, text="Smart Recorder", text_color="cyan")
        self.lbl_smart.pack(pady=(10, 0))
        
        self.btn_smart_rec = ctk.CTkButton(self.left_frame, text="🔴 Kaydı Başlat", command=self.toggle_smart_recording, fg_color="#E91E63", hover_color="#C2185B")
        self.btn_smart_rec.pack(pady=5, padx=10, fill="x")

        
        btn_snap_assert = ctk.CTkButton(self.left_frame, text="📸 Record Check", command=self.smart_record_assert, fg_color="#E91E63", hover_color="#C2185B")
        btn_snap_assert.pack(pady=5, padx=10, fill="x")

        # Basic Actions
        self.lbl_basic = ctk.CTkLabel(self.left_frame, text="Temel Aksiyonlar", text_color="gray")
        self.lbl_basic.pack(pady=(10, 0))

        actions = [
            ("🖱️ Sol Tıkla (Manuel)", self.add_click_action),
            ("🖱️ Sağ Tıkla (Manuel)", self.add_right_click_action),
            ("✍️ Type", self.add_type_action),
            ("⌨️ Tuş Bas", self.add_key_press_action),
            ("↕️ Kaydır (Scroll)", self.add_scroll_action),
            ("🔍 Metne Tıkla (OCR)", self.add_ocr_click_action),
            ("📖 Metin Oku (OCR)", self.add_ocr_read_action),
            ("⏳ Wait", self.add_wait_action),
            ("🚀 Launch App", self.add_launch_action),
            ("✅ Assert (Manuel)", self.add_assert_action),
        ]

        for text, cmd in actions:
            btn = ctk.CTkButton(self.left_frame, text=text, command=cmd)
            btn.pack(pady=3, padx=10, fill="x")

        self.lbl_repo = ctk.CTkLabel(self.left_frame, text="Repository", text_color="cyan")
        self.lbl_repo.pack(pady=(15, 0))

        self.btn_assets = ctk.CTkButton(self.left_frame, text="🖼️ Görsel Kütüphanesi", command=self.show_asset_browser, fg_color="#673AB7", hover_color="#512DA8")
        self.btn_assets.pack(pady=5, padx=10, fill="x")

        self.lbl_val = ctk.CTkLabel(self.left_frame, text="Doğrulama", text_color="cyan")
        self.lbl_val.pack(pady=(15, 0))

        self.btn_add_validation = ctk.CTkButton(self.left_frame, text="✅ Doğrulama Ekle", command=self.add_validation_action, fg_color="#00BCD4", hover_color="#00ACC1")
        self.btn_add_validation.pack(pady=5, padx=10, fill="x")

    def _setup_main_panel(self):
        """Senaryo Adımları Listesi"""
        self.main_frame = ctk.CTkFrame(self, corner_radius=0)
        self.main_frame.grid(row=0, column=1, sticky="nswe", padx=10, pady=10)
        
        header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=5)
        
        self.lbl_scenario = ctk.CTkLabel(header_frame, text="Senaryo Adımları", font=("Arial", 16, "bold"))
        self.lbl_scenario.pack(side="left", padx=10)
        
        self.btn_clear_all = ctk.CTkButton(header_frame, text="🗑️ Temizle", width=80, fg_color="red", command=self.clear_all_steps)
        self.btn_clear_all.pack(side="right", padx=10)

        self.scrollable_steps = ctk.CTkScrollableFrame(self.main_frame, label_text="Adım Listesi")
        self.scrollable_steps.pack(expand=True, fill="both", padx=10, pady=5)

    def _setup_right_panel(self):
        """Kontrol ve Log Paneli"""
        self.right_frame = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.right_frame.grid(row=0, column=2, sticky="nswe")

        self.lbl_controls = ctk.CTkLabel(self.right_frame, text="Kontrol Paneli", font=("Arial", 16, "bold"))
        self.lbl_controls.pack(pady=10)

        self.btn_run = ctk.CTkButton(self.right_frame, text="▶️ Çalıştır", command=self.run_scenario, fg_color="green")
        self.btn_run.pack(pady=10, padx=10, fill="x")

        self.btn_stop = ctk.CTkButton(self.right_frame, text="⛔ Durdur", command=self.stop_scenario, fg_color="red")
        self.btn_stop.pack(pady=10, padx=10, fill="x")
        
        self.btn_save = ctk.CTkButton(self.right_frame, text="💾 Kaydet", command=self.save_to_db, fg_color="#2196F3")
        self.btn_save.pack(pady=5, padx=10, fill="x")

        self.btn_load = ctk.CTkButton(self.right_frame, text="📂 Senaryolar", command=self.show_scenarios, fg_color="#2196F3")
        self.btn_load.pack(pady=5, padx=10, fill="x")

        # Open Data Folder Button (v30)
        from core.config import open_data_folder
        self.btn_open_data = ctk.CTkButton(self.right_frame, text="📁 Veri Klasörünü Aç", command=open_data_folder, fg_color="#FF9800", hover_color="#F57C00")
        self.btn_open_data.pack(pady=5, padx=10, fill="x")

        # Global Speed Control
        self.lbl_speed = ctk.CTkLabel(self.right_frame, text="İşlem Gecikmesi (sn): 0.5", text_color="gray")
        self.lbl_speed.pack(pady=(20, 0))
        
        self.slider_speed = ctk.CTkSlider(self.right_frame, from_=0, to=5, number_of_steps=50, command=self.on_speed_change)
        self.slider_speed.set(0.5)
        self.slider_speed.pack(pady=5, padx=10, fill="x")

        
        self.textbox_log = ctk.CTkTextbox(self.right_frame)
        self.textbox_log.pack(expand=True, fill="both", padx=10, pady=10)

    def _setup_logging(self):
        class TextHandler(logging.Handler):
            def __init__(self, text_widget):
                super().__init__()
                self.widget = text_widget

            def emit(self, record):
                msg = self.format(record)
                # Thread-safe UI update
                self.widget.after(0, lambda m=msg: self._safe_append(m))
            
            def _safe_append(self, msg):
                self.widget.insert("end", msg + "\n")
                self.widget.see("end")

        # Global log level force
        logging.getLogger().setLevel(logging.INFO)
        handler = TextHandler(self.textbox_log)
        # Sadece bizim loglarımızı daha temiz göster
        formatter = logging.Formatter('%(levelname)s: %(message)s')
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)


    def refresh_step_list(self):
        for widget in self.scrollable_steps.winfo_children():
            widget.destroy()

        for idx, action in enumerate(self.current_scenario.actions):
            frame = ctk.CTkFrame(self.scrollable_steps, height=40)
            frame.pack(pady=2, padx=5, fill="x")
            
            # Drag & Drop Bindings
            bind_cmd = lambda e, i=idx: self.on_drag_start(e, i)
            motion_cmd = self.on_drag_motion
            drop_cmd = lambda e, i=idx: self.on_drop(e, i)

            frame.bind("<Button-1>", bind_cmd)
            frame.bind("<B1-Motion>", motion_cmd)
            frame.bind("<ButtonRelease-1>", drop_cmd)
            
            # Adım Bilgisi
            lbl_text = f"{idx+1}. {action.type}"
            button_type = action.params.get("button", "left")
            btn_label = "(Sağ)" if button_type == "right" else "(Sol)"

            if action.type == "CLICK":
                lbl_text += f" {btn_label}"
                if action.params.get("by_image"):
                    lbl_text += f" (Img: {os.path.basename(action.params['target'])})"
            elif action.type == "CLICK_TEXT":
                lbl_text += f" {btn_label} ('{action.params.get('text')}')"
            elif action.type == "TYPE":
                lbl_text += f" ('{action.params['text']}')"
            else:
                lbl_text += f" - {action.description}"
                
            lbl = ctk.CTkLabel(frame, text=lbl_text, anchor="w")
            lbl.pack(side="left", padx=5, expand=True, fill="x")
            
            # Label'a da bind ekle (event'in frame'den geçmesi için)
            lbl.bind("<Button-1>", bind_cmd)
            lbl.bind("<B1-Motion>", motion_cmd)
            lbl.bind("<ButtonRelease-1>", drop_cmd)
            
            # Kontrol Butonları (Yukarı/Aşağı/Sil)
            btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
            btn_frame.pack(side="right", padx=5)

            btn_up = ctk.CTkButton(btn_frame, text="⬆", width=30, fg_color="gray", command=lambda i=idx: self.move_step_up(i))
            btn_up.pack(side="left", padx=2)
            
            btn_down = ctk.CTkButton(btn_frame, text="⬇", width=30, fg_color="gray", command=lambda i=idx: self.move_step_down(i))
            btn_down.pack(side="left", padx=2)
            
            btn_del = ctk.CTkButton(btn_frame, text="❌", width=30, fg_color="darkred", command=lambda i=idx: self.delete_step(i))
            btn_del.pack(side="left", padx=2)


    def delete_step(self, index):
        if 0 <= index < len(self.current_scenario.actions):
            self.current_scenario.actions.pop(index)
            self.refresh_step_list()

    def move_step_up(self, index):
        if index > 0:
            self.current_scenario.actions[index], self.current_scenario.actions[index-1] = self.current_scenario.actions[index-1], self.current_scenario.actions[index]
            self.refresh_step_list()

    def move_step_down(self, index):
        if index < len(self.current_scenario.actions) - 1:
            self.current_scenario.actions[index], self.current_scenario.actions[index+1] = self.current_scenario.actions[index+1], self.current_scenario.actions[index]
            self.refresh_step_list()
            
    def clear_all_steps(self):
        if messagebox.askyesno("Onay", "Tüm adımları silmek istediğinize emin misiniz?"):
            self.current_scenario.actions = []
            self.refresh_step_list()

    def on_drag_start(self, event, index):
        self.drag_index = index
        self.scrollable_steps.configure(cursor="hand2")
        # Görsel geri bildirim: Seçili olanı belirginleştir
        for i, child in enumerate(self.scrollable_steps.winfo_children()):
            if i == index:
                child.configure(fg_color="#3B3B3B") # Hafif gri/reaktif renk

    def on_drag_motion(self, event):
        pass

    def on_drop(self, event, index):
        self.scrollable_steps.configure(cursor="")
        if self.drag_index is not None:
            source_idx = self.drag_index
            target_idx = None
            
            x, y = self.winfo_pointerxy()
            for i, child in enumerate(self.scrollable_steps.winfo_children()):
                if isinstance(child, ctk.CTkFrame):
                    # Rengi eski haline getir
                    child.configure(fg_color=["#3B3B3B", "#2B2B2B"]) # CTK default
                    
                    x1 = child.winfo_rootx()
                    y1 = child.winfo_rooty()
                    x2 = x1 + child.winfo_width()
                    y2 = y1 + child.winfo_height()
                    
                    if x1 <= x <= x2 and y1 <= y <= y2:
                        target_idx = i

            if target_idx is not None and source_idx != target_idx:
                action = self.current_scenario.actions.pop(source_idx)
                self.current_scenario.actions.insert(target_idx, action)
                self.refresh_step_list()
            else:
                self.refresh_step_list() # Rengi sıfırlamak için
        
        self.drag_index = None

    # --- Smart Recorder Methods ---
    def toggle_smart_recording(self):
        if self.recorder and self.recorder.is_recording:
            self.recorder.stop()
        else:
            # Başlat
            self.iconify() # Arayüzü gizle
            self.recorder = Recorder(
                on_action_recorded=self.on_action_recorded_callback,
                on_stop=self.on_recorder_stop,
                exclude_window=self
            )
            self.recorder.start()
            self.btn_smart_rec.configure(text="⏹ Kaydı Bitir (ESC)")

    def on_action_recorded_callback(self, action_type, params):
        # Thread güvenliği için after kullanıyoruz
        self.after(0, lambda: self._add_recorded_action(action_type, params))

    def _add_recorded_action(self, action_type, params):
        description = f"Auto: {action_type}"
        if action_type == "CLICK":
            description = f"Click Image: {os.path.basename(params['target'])}"
            # Otomatik kaydı da kütüphaneye ekle
            asset_name = f"auto_{datetime.datetime.now().strftime('%H%M%S')}"
            self.db.save_asset(asset_name, params['target'])
            
        action = Action(type=action_type, params=params, description=description)
        self.current_scenario.add_action(action)
        self.refresh_step_list()

    def on_recorder_stop(self):
        self.after(0, self._on_recorder_stop_ui)

    def _on_recorder_stop_ui(self):
        self.deiconify() # Arayüzü geri getir
        self.btn_smart_rec.configure(text="📸 Kaydı Başlat")
        messagebox.showinfo("Kayıt Tamamlandı", "Otomatik kayıt sonlandırıldı.")

    def smart_record_click(self):

        self.start_snip_tool(self._on_record_click_complete)
        
    def smart_record_assert(self):
        self.start_snip_tool(self._on_record_assert_complete)
        
    def start_snip_tool(self, callback):
        # UI'ı küçült ki ekran rahat görünsün
        self.iconify()
        # Snip aracı bittiğinde UI geri gelsin
        def wrapped_callback(filepath):
            self.deiconify()
            if filepath:
                callback(filepath)
        
        SnipTool(self, wrapped_callback).start_selection()
        
    def _on_record_click_complete(self, filepath):
        action = Action(type="CLICK", params={"target": filepath, "by_image": True}, description=f"Click Image: {os.path.basename(filepath)}")
        self.current_scenario.add_action(action)
        self.refresh_step_list()
        
    def _on_record_assert_complete(self, filepath):
        action = Action(type="ASSERT_EXISTS", params={"target": filepath}, description=f"Assert Image: {os.path.basename(filepath)}")
        self.current_scenario.add_action(action)
        self.refresh_step_list()

    
    # --- Aksiyon Ekleme Fonksiyonları ---
    def add_click_action(self):
        # Koordinat sormayı tamamen kaldırdık, direkt SnipTool başlatıyoruz
        self.start_snip_tool(self._on_manual_click_snip_complete)

    def _on_manual_click_snip_complete(self, filepath):
        # Görseli kütüphaneye de kaydedelim
        dialog = ctk.CTkInputDialog(text="Görsel için bir isim verin:", title="Kütüphaneye Kaydet")
        name = dialog.get_input()
        if not name:
            name = f"manual_click_{os.path.basename(filepath)}"
        
        # DB'ye kaydet
        self.db.save_asset(name, filepath)
        
        action = Action(type="CLICK", params={"target": filepath, "by_image": True}, description=f"Click: {name}")
        self.current_scenario.add_action(action)
        self.refresh_step_list()

    def add_right_click_action(self):
        file_path = filedialog.askopenfilename(
            initialdir=os.path.join(os.getcwd(), "assets"),
            title="Sağ tıklanacak görseli seçin",
            filetypes=(("PNG files", "*.png"), ("all files", "*.*"))
        )
        if file_path:
            description = f"Sağ Tıkla: {os.path.basename(file_path)}"
            action = Action(type="CLICK", params={"target": file_path, "by_image": True, "button": "right"}, description=description)
            self.current_scenario.add_action(action)
            self.refresh_step_list()

    def add_type_action(self):
        dialog = ctk.CTkInputDialog(text="Yazılacak metin:", title="Type Action")
        text = dialog.get_input()
        if text:
            action = Action(type="TYPE", params={"text": text}, description=f"Type '{text}'")
            self.current_scenario.add_action(action)
            self.refresh_step_list()

    def add_key_press_action(self):
        # Özel tuş seçimi için diyalog
        dialog = ctk.CTkToplevel(self)
        dialog.title("Tuş Seç")
        dialog.geometry("300x200")
        dialog.grab_set()
        
        lbl = ctk.CTkLabel(dialog, text="Basılacak özel tuşu seçin:")
        lbl.pack(pady=10)
        
        keys = ["enter", "tab", "esc", "backspace", "delete", "space", "home", "end", "pgup", "pgdn", "up", "down", "left", "right", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12"]
        
        combo = ctk.CTkComboBox(dialog, values=keys)
        combo.pack(pady=10)
        combo.set("enter")
        
        def add():
            key = combo.get()
            action = Action(type="PRESS_KEY", params={"key": key}, description=f"Press Key: {key}")
            self.current_scenario.add_action(action)
            self.refresh_step_list()
            dialog.destroy()
            
        btn = ctk.CTkButton(dialog, text="Ekle", command=add)
        btn.pack(pady=10)

    def add_scroll_action(self):
        dialog = ctk.CTkInputDialog(text="Scroll Miktarı (Örn: -500 Aşağı, 500 Yukarı):", title="Scroll Action")
        amount = dialog.get_input()
        if amount:
            try:
                amt = int(amount)
                action = Action(type="SCROLL", params={"amount": amt}, description=f"Scroll: {amt}")
                self.current_scenario.add_action(action)
                self.refresh_step_list()
            except ValueError:
                messagebox.showerror("Hata", "Lütfen geçerli bir sayı girin.")

    def add_ocr_click_action(self):
        dialog = ctk.CTkInputDialog(text="Tıklanacak Metin:", title="OCR Click")
        text = dialog.get_input()
        if text:
            action = Action(type="CLICK_TEXT", params={"text": text}, description=f"OCR Click: '{text}'")
            self.current_scenario.add_action(action)
            self.refresh_step_list()

    def add_ocr_read_action(self):
        messagebox.showinfo("Bilgi", "Okunacak bölgeyi seçmek için mouse ile sürükleyin.")
        self.withdraw()
        snip = SnipTool(self)
        self.wait_window(snip)
        self.deiconify()
        
        if snip.start_x and snip.end_x:
            x1, y1 = min(snip.start_x, snip.end_x), min(snip.start_y, snip.end_y)
            x2, y2 = max(snip.start_x, snip.end_x), max(snip.start_y, snip.end_y)
            region = (x1, y1, x2-x1, y2-y1)
            
            action = Action(type="READ_TEXT", params={"region": region}, description=f"OCR Read Area: {region}")
            self.current_scenario.add_action(action)
            self.refresh_step_list()

    def add_wait_action(self):
        dialog = ctk.CTkInputDialog(text="Süre (saniye):", title="Wait Action")
        seconds = dialog.get_input()
        if seconds:
            action = Action(type="WAIT", params={"seconds": seconds}, description=f"Wait {seconds}s")
            self.current_scenario.add_action(action)
            self.refresh_step_list()
            
    def add_launch_action(self):
        file_path = filedialog.askopenfilename(title="Uygulama Seç", filetypes=[("Executables", "*.exe"), ("All Files", "*.*")])
        if file_path:
            action = Action(type="LAUNCH_APP", params={"path": file_path}, description=f"Open {os.path.basename(file_path)}")
            self.current_scenario.add_action(action)
            self.refresh_step_list()
            
    def add_assert_action(self):
        target = filedialog.askopenfilename(title="Aranacak Görseli Seç", filetypes=[("Images", "*.png;*.jpg;*.jpeg")])
        if target:
            action = Action(type="ASSERT_EXISTS", params={"target": target}, description=f"Assert Exists: {os.path.basename(target)}")
            self.current_scenario.add_action(action)
            self.refresh_step_list()

    # --- Çalıştırma ve Kayıt ---
    def on_speed_change(self, value):
        self.runner.action_delay = float(value)
        self.lbl_speed.configure(text=f"İşlem Gecikmesi (sn): {value:.1f}")

    def run_scenario(self):
        self.btn_run.configure(state="disabled")
        self.runner.run_scenario(
            self.current_scenario, 
            on_finish=self.on_scenario_finish
        )

    def stop_scenario(self):
        self.runner.stop()

    def on_scenario_finish(self, success, error_msg):
        self.btn_run.configure(state="normal")
        status = "Başarılı" if success else "Hata"
        messagebox.showinfo("Sonuç", f"Senaryo tamamlandı: {status}\n{error_msg}")

    # --- Database Operations ---
    def save_to_db(self):
        if not self.current_scenario.actions:
            messagebox.showwarning("Uyarı", "Kaydedilecek adım yok.")
            return
            
        dialog = ctk.CTkInputDialog(text="Senaryo Adı:", title="Kaydet")
        name = dialog.get_input()
        if name:
            self.current_scenario.name = name
            res = self.db.save_scenario(self.current_scenario)
            if res:
                messagebox.showinfo("Başarılı", f"Senaryo veritabanına kaydedildi. ID: {res}")
            else:
                messagebox.showerror("Hata", "Veritabanına kaydedilemedi.")

    def show_scenarios(self):
        browser = DatabaseBrowser(self, self.db, self.on_load_from_db)
        browser.grab_set()

    def on_load_from_db(self, scenario):
        self.current_scenario = scenario
        self.refresh_step_list()
        messagebox.showinfo("Yüklendi", f"'{scenario.name}' senaryosu yüklendi.")

    def add_validation_action(self):
        # Seçenekler sunan bir pencere aç
        dialog = ctk.CTkToplevel(self)
        dialog.title("Doğrulama Türü Seç")
        dialog.geometry("300x200")
        dialog.grab_set()
        
        lbl = ctk.CTkLabel(dialog, text="Hangi tür doğrulama eklemek istersiniz?", wraplength=250)
        lbl.pack(pady=10)
        
        def pick_window():
            dialog.destroy()
            title = ctk.CTkInputDialog(text="Kontrol edilecek pencere başlığı:", title="Pencere Doğrulama").get_input()
            if title:
                action = Action(type="VALIDATE_WINDOW", params={"title": title, "timeout": 5}, description=f"Validate Window: {title}")
                self.current_scenario.add_action(action)
                self.refresh_step_list()

        def pick_element():
            dialog.destroy()
            win_title = ctk.CTkInputDialog(text="Pencere başlığı:", title="Element Doğrulama").get_input()
            if not win_title: return
            el_name = ctk.CTkInputDialog(text="Element adı (Buton/Yazı):", title="Element Doğrulama").get_input()
            if el_name:
                action = Action(type="VALIDATE_ELEMENT", params={"window_title": win_title, "element_name": el_name, "timeout": 5}, description=f"Validate Element '{el_name}' in '{win_title}'")
                self.current_scenario.add_action(action)
                self.refresh_step_list()

        btn_win = ctk.CTkButton(dialog, text="Pencere Açık mı?", command=pick_window)
        btn_win.pack(pady=5, padx=20, fill="x")
        
        btn_el = ctk.CTkButton(dialog, text="Element/Buton Var mı?", command=pick_element)
        btn_el.pack(pady=5, padx=20, fill="x")

    def show_asset_browser(self):
        browser = AssetBrowser(self, self.db, self.on_asset_selected)
        browser.grab_set()

    def on_asset_selected(self, asset_path, asset_name):
        action = Action(type="CLICK", params={"target": asset_path, "by_image": True}, description=f"Click (Repo): {asset_name}")
        self.current_scenario.add_action(action)
        self.refresh_step_list()
        messagebox.showinfo("Eklendi", f"'{asset_name}' kütüphaneden senaryoya eklendi.")


class AssetBrowser(ctk.CTkToplevel):
    def __init__(self, master, db, callback):
        super().__init__(master)
        self.title("Görsel Kütüphanesi")
        self.geometry("500x600")
        self.db = db
        self.callback = callback
        
        self.lbl = ctk.CTkLabel(self, text="Kayıtlı Görseller", font=("Arial", 16, "bold"))
        self.lbl.pack(pady=10)
        
        self.scrollable_frame = ctk.CTkScrollableFrame(self)
        self.scrollable_frame.pack(expand=True, fill="both", padx=10, pady=10)
        
        self.refresh_list()
        
    def refresh_list(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
            
        assets = self.db.list_assets()
        for a_id, name, path, created in assets:
            frame = ctk.CTkFrame(self.scrollable_frame)
            frame.pack(fill="x", pady=5)
            
            # Simple metadata text
            lbl_info = ctk.CTkLabel(frame, text=name, anchor="w")
            lbl_info.pack(side="left", padx=10, expand=True, fill="x")
            
            btn_use = ctk.CTkButton(frame, text="Ekle", width=60, command=lambda p=path, n=name: self.use_asset(p, n))
            btn_use.pack(side="right", padx=5)
            
            btn_del = ctk.CTkButton(frame, text="🗑️", width=30, fg_color="red", command=lambda i=a_id: self.delete_asset(i))
            btn_del.pack(side="right", padx=2)

    def use_asset(self, path, name):
        self.callback(path, name)
        self.destroy()

    def delete_asset(self, a_id):
        if messagebox.askyesno("Onay", "Bu görseli kütüphaneden silmek istediğinize emin misiniz?"):
            if self.db.delete_asset(a_id):
                self.refresh_list()
            else:
                messagebox.showerror("Hata", "Silinemedi.")


class DatabaseBrowser(ctk.CTkToplevel):
    def __init__(self, master, db, callback):
        super().__init__(master)
        self.title("Senaryo Kütüphanesi")
        self.geometry("400x500")
        self.db = db
        self.callback = callback
        
        self.lbl = ctk.CTkLabel(self, text="Kayıtlı Senaryolar", font=("Arial", 16, "bold"))
        self.lbl.pack(pady=10)
        
        self.scrollable_frame = ctk.CTkScrollableFrame(self)
        self.scrollable_frame.pack(expand=True, fill="both", padx=10, pady=10)
        
        self.refresh_list()
        
    def refresh_list(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
            
        scenarios = self.db.list_scenarios()
        for s_id, name, desc, created in scenarios:
            frame = ctk.CTkFrame(self.scrollable_frame)
            frame.pack(fill="x", pady=2)
            
            lbl_name = ctk.CTkLabel(frame, text=f"{name}\n({created[:16]})", anchor="w", justify="left")
            lbl_name.pack(side="left", padx=5, expand=True, fill="x")
            
            btn_load = ctk.CTkButton(frame, text="Seç", width=60, command=lambda i=s_id: self.load_one(i))
            btn_load.pack(side="right", padx=5, pady=5)
            
            btn_del = ctk.CTkButton(frame, text="🗑️", width=30, fg_color="red", command=lambda i=s_id: self.delete_one(i))
            btn_del.pack(side="right", padx=2)

    def load_one(self, s_id):
        scenario = self.db.load_scenario_by_id(s_id)
        if scenario:
            self.callback(scenario)
            self.destroy()

    def delete_one(self, s_id):
        if messagebox.askyesno("Onay", "Bu senaryoyu silmek istediğinize emin misiniz?"):
            if self.db.delete_scenario(s_id):
                self.refresh_list()
            else:
                messagebox.showerror("Hata", "Silinemedi.")
