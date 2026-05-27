# -*- coding: utf-8 -*-
"""
Dokunmatik PC - EKRAN + DOKUNMATIK gorsel test araci
====================================================
Kurulum gerektirmez (Python'un kendi tkinter'i yeter; Python 3.8+).
Calistir:   python display_touch_test.py

Testler:
  1) Renk doldurma        - dead pixel / renk bozuklugu icin tam ekran renkler
  2) Gradyan / izgara     - panel uniform mu, geometri/olcek dogru mu
  3) Dokunmatik cizim     - parmakla cizim, basinc/iz takibi
  4) Dokunmatik izgara    - ekranin her hucresine dokunulduguna emin ol
  5) Cok-nokta (multitouch) - ayni anda birden cok parmak takibi

KISAYOLLAR (her test ekraninda):
  ESC / sag tik  -> menuye don
  BOSLUK / sol tik -> renk/desen testlerinde sonraki adim
"""

import tkinter as tk

PALETTE = [
    ("Kirmizi", "#FF0000"), ("Yesil", "#00FF00"), ("Mavi", "#0000FF"),
    ("Beyaz", "#FFFFFF"), ("Siyah", "#000000"),
    ("Gri %50", "#808080"), ("Cyan", "#00FFFF"),
    ("Magenta", "#FF00FF"), ("Sari", "#FFFF00"),
]


class App:
    def __init__(self, root):
        self.root = root
        root.title("Dokunmatik PC - Ekran & Dokunmatik Test")
        root.attributes("-fullscreen", True)
        root.configure(bg="#101418")
        root.bind("<Escape>", lambda e: self.show_menu())
        self.frame = None
        self.show_menu()

    # ---------- yardimci ----------
    def clear(self):
        if self.frame is not None:
            self.frame.destroy()
        self.frame = tk.Frame(self.root, bg="#101418")
        self.frame.pack(fill="both", expand=True)
        return self.frame

    # ---------- ANA MENU ----------
    def show_menu(self):
        f = self.clear()
        tk.Label(f, text="DOKUNMATIK PC  -  EKRAN & DOKUNMATIK TEST",
                 font=("Segoe UI", 28, "bold"), fg="#7fd1ff", bg="#101418").pack(pady=(60, 10))
        tk.Label(f, text="Bir test secin  -  her testte ESC ile menuye donersiniz",
                 font=("Segoe UI", 14), fg="#aab", bg="#101418").pack(pady=(0, 40))

        buttons = [
            ("1  Renk Doldurma (dead pixel)", self.test_colors),
            ("2  Gradyan / Izgara (uniform & geometri)", self.test_pattern),
            ("3  Dokunmatik Cizim", self.test_draw),
            ("4  Dokunmatik Izgara Kapsama", self.test_touch_grid),
            ("5  Cok-Nokta (Multitouch)", self.test_multitouch),
        ]
        for text, cmd in buttons:
            tk.Button(f, text=text, font=("Segoe UI", 18), width=40, height=2,
                      bg="#1d2630", fg="white", activebackground="#2d3a48",
                      relief="flat", command=cmd).pack(pady=8)

        tk.Button(f, text="CIKIS", font=("Segoe UI", 14), bg="#5a1d1d", fg="white",
                  relief="flat", width=20, command=self.root.destroy).pack(pady=(40, 0))

    # ---------- 1) RENK DOLDURMA ----------
    def test_colors(self):
        f = self.clear()
        self.idx = 0
        cv = tk.Canvas(f, highlightthickness=0)
        cv.pack(fill="both", expand=True)
        lbl = tk.Label(cv, font=("Segoe UI", 16), bg="#000", fg="#888")

        def show(i):
            name, color = PALETTE[i % len(PALETTE)]
            cv.configure(bg=color)
            fg = "#000000" if color in ("#FFFFFF", "#FFFF00", "#00FFFF") else "#888888"
            lbl.configure(text=f"{name}   ({i+1}/{len(PALETTE)})   "
                               f"sol tik/bosluk: sonraki  -  ESC: menu",
                          bg=color, fg=fg)
            lbl.place(relx=0.5, rely=0.97, anchor="s")

        def nxt(_=None):
            self.idx += 1
            if self.idx >= len(PALETTE):
                self.show_menu()
            else:
                show(self.idx)

        show(0)
        cv.bind("<Button-1>", nxt)
        cv.bind("<Button-3>", lambda e: self.show_menu())
        self.root.bind("<space>", nxt)

    # ---------- 2) GRADYAN / IZGARA ----------
    def test_pattern(self):
        f = self.clear()
        cv = tk.Canvas(f, highlightthickness=0, bg="black")
        cv.pack(fill="both", expand=True)
        self.pat = 0

        def draw(_=None):
            cv.delete("all")
            w = self.root.winfo_screenwidth()
            h = self.root.winfo_screenheight()
            if self.pat == 0:   # yatay gri gradyan
                steps = 64
                for i in range(steps):
                    v = int(255 * i / (steps - 1))
                    cv.create_rectangle(i*w/steps, 0, (i+1)*w/steps, h,
                                        fill=f"#{v:02x}{v:02x}{v:02x}", outline="")
                txt = "Gri gradyan - bant/renk sapmasi var mi?"
            elif self.pat == 1:  # izgara (geometri/olcek)
                gap = 40
                for x in range(0, w, gap):
                    cv.create_line(x, 0, x, h, fill="#00ff00")
                for y in range(0, h, gap):
                    cv.create_line(0, y, w, y, fill="#00ff00")
                cv.create_rectangle(2, 2, w-2, h-2, outline="#ff0000", width=3)
                txt = "Izgara - kenarlar tam gorunuyor mu, kareler esit mi?"
            else:               # kenar/kose isaretleri
                m = 60
                for (cx, cy) in [(m, m), (w-m, m), (m, h-m), (w-m, h-m)]:
                    cv.create_oval(cx-30, cy-30, cx+30, cy+30, outline="#ffffff", width=3)
                cv.create_oval(w/2-30, h/2-30, w/2+30, h/2+30, outline="#ffff00", width=3)
                txt = "Koseler ve merkez - hepsi gorunuyor mu (overscan)?"
            cv.create_text(w/2, h-20, text=txt + "   |   tik: sonraki  -  ESC: menu",
                           fill="#ffffff", font=("Segoe UI", 14))

        def nxt(_=None):
            self.pat += 1
            if self.pat > 2:
                self.show_menu()
            else:
                draw()

        self.root.after(80, draw)  # ekran boyutu hazir olsun
        cv.bind("<Button-1>", nxt)
        cv.bind("<Button-3>", lambda e: self.show_menu())

    # ---------- 3) DOKUNMATIK CIZIM ----------
    def test_draw(self):
        f = self.clear()
        cv = tk.Canvas(f, bg="black", highlightthickness=0)
        cv.pack(fill="both", expand=True)
        self.last = {}

        def down(e):
            self.last[1] = (e.x, e.y)

        def move(e):
            p = self.last.get(1)
            if p:
                cv.create_line(p[0], p[1], e.x, e.y, fill="#00ff66", width=4,
                               capstyle="round", smooth=True)
            self.last[1] = (e.x, e.y)
            cv.create_oval(e.x-2, e.y-2, e.x+2, e.y+2, fill="#ffffff", outline="")

        def up(_):
            self.last.pop(1, None)

        cv.bind("<Button-1>", down)
        cv.bind("<B1-Motion>", move)
        cv.bind("<ButtonRelease-1>", up)
        cv.bind("<Button-3>", lambda e: self.show_menu())
        cv.create_text(self.root.winfo_screenwidth()//2 or 600, 30,
                       text="Parmagini gezdir - kesintisiz iz cizmeli   |   sag tik/ESC: menu",
                       fill="#888", font=("Segoe UI", 14))
        tk.Button(f, text="Temizle", command=lambda: (cv.delete("all")),
                  bg="#1d2630", fg="white", relief="flat").place(x=20, y=20)

    # ---------- 4) DOKUNMATIK IZGARA KAPSAMA ----------
    def test_touch_grid(self):
        f = self.clear()
        cv = tk.Canvas(f, bg="#111", highlightthickness=0)
        cv.pack(fill="both", expand=True)
        cols, rows = 8, 5
        self.cells = {}
        self.touched = set()

        def build():
            cv.delete("all")
            w = self.root.winfo_screenwidth()
            h = self.root.winfo_screenheight()
            cw, ch = w/cols, h/rows
            self.cellsize = (cw, ch)
            for r in range(rows):
                for c in range(cols):
                    x0, y0 = c*cw, r*ch
                    rect = cv.create_rectangle(x0+2, y0+2, x0+cw-2, y0+ch-2,
                                               fill="#26323d", outline="#3a4a5a")
                    self.cells[(c, r)] = rect
            cv.create_text(w/2, h/2, text="Her kareye dokun",
                           fill="#566", font=("Segoe UI", 20), tags="hint")

        def touch(e):
            cw, ch = self.cellsize
            c, r = int(e.x//cw), int(e.y//ch)
            if (c, r) in self.cells and (c, r) not in self.touched:
                self.touched.add((c, r))
                cv.itemconfig(self.cells[(c, r)], fill="#00aa55")
                if len(self.touched) == cols*rows:
                    cv.delete("hint")
                    cv.create_text(self.root.winfo_screenwidth()/2,
                                   self.root.winfo_screenheight()/2,
                                   text="TUM HUCRELER OK  -  ESC ile cik",
                                   fill="#0f0", font=("Segoe UI", 28, "bold"))

        self.root.after(80, build)
        cv.bind("<Button-1>", touch)
        cv.bind("<B1-Motion>", touch)
        cv.bind("<Button-3>", lambda e: self.show_menu())

    # ---------- 5) MULTITOUCH ----------
    def test_multitouch(self):
        """
        Tkinter cok-nokta olaylarini sinirli destekler; Windows'ta dokunma
        olaylari fare olarak gelir. Bu test yine de cizim + iz sayar.
        Gercek multitouch dogrulamasi icin Windows 'tabtip' / cizim uygulamasi
        onerilir; burada eszamanli iz gorsellestirilir.
        """
        f = self.clear()
        cv = tk.Canvas(f, bg="black", highlightthickness=0)
        cv.pack(fill="both", expand=True)
        colors = ["#ff4d4d", "#4dff4d", "#4d4dff", "#ffff4d", "#ff4dff"]

        def paint(e):
            cv.create_oval(e.x-25, e.y-25, e.x+25, e.y+25,
                           outline=colors[(e.x+e.y) % len(colors)], width=4)

        cv.bind("<Button-1>", paint)
        cv.bind("<B1-Motion>", paint)
        cv.bind("<Button-3>", lambda e: self.show_menu())
        cv.create_text(self.root.winfo_screenwidth()//2 or 600, 30,
                       text="Birden cok parmakla dokun - her temas halka birakir   |   ESC: menu",
                       fill="#888", font=("Segoe UI", 14))
        tk.Button(f, text="Temizle", command=lambda: cv.delete("all"),
                  bg="#1d2630", fg="white", relief="flat").place(x=20, y=20)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
