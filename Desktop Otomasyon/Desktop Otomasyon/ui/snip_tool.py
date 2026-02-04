import tkinter as tk
from PIL import ImageGrab
import os
import datetime

class SnipTool(tk.Toplevel):
    def __init__(self, master, on_snip_complete):
        super().__init__(master)
        self.withdraw() # Pencereyi gizle (başlangıçta)
        self.attributes('-fullscreen', True)
        self.attributes('-alpha', 0.3)
        self.attributes('-topmost', True)
        self.configure(background='black')
        self.overrideredirect(True) # Pencere kenarlıklarını kaldır

        self.on_snip_complete = on_snip_complete
        self.start_x = None
        self.start_y = None
        self.current_rect = None

        self.canvas = tk.Canvas(self, cursor="cross", bg="grey11")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_move_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        
        # ESC ile çıkış
        self.bind("<Escape>", lambda e: self.destroy())

    def start_selection(self):
        """Seçim ekranını başlatır."""
        self.deiconify() # Pencereyi göster
        self.focus_set()

    def on_button_press(self, event):
        self.start_x = self.canvas.canvasx(event.x)
        self.start_y = self.canvas.canvasy(event.y)
        
        if self.current_rect:
            self.canvas.delete(self.current_rect)
        
        self.current_rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y, 
            outline='red', width=2
        )

    def on_move_press(self, event):
        cur_x = self.canvas.canvasx(event.x)
        cur_y = self.canvas.canvasy(event.y)
        self.canvas.coords(self.current_rect, self.start_x, self.start_y, cur_x, cur_y)

    def on_button_release(self, event):
        end_x = self.canvas.canvasx(event.x)
        end_y = self.canvas.canvasy(event.y)
        
        # Koordinatları sırala (soldan sağa, yukarıdan aşağıya)
        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)

        # Çok küçükse iptal et (yanlışlıkla tıklama)
        if (x2 - x1) < 5 or (y2 - y1) < 5:
            self.destroy()
            return

        self.destroy() # Pencereyi kapat
        self.capture_screen(x1, y1, x2, y2)

    def capture_screen(self, x1, y1, x2, y2):
        """Ekrandan belirtilen alanı keser ve kaydeder."""
        try:
            from core.config import ASSETS_DIR
            filename = f"snip_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            filepath = os.path.join(ASSETS_DIR, filename)

            # Ekran görüntüsü al
            # ImageGrab.grab(bbox=(x1, y1, x2, y2)) bazı sistemlerde scaling yüzünden kayabilir.
            # Şimdilik direkt koordinatları deniyoruz.
            img = ImageGrab.grab(bbox=(x1, y1, x2, y2))
            img.save(filepath)
            
            if self.on_snip_complete:
                self.on_snip_complete(filepath)
                
        except Exception as e:
            print(f"Hata: {e}")
