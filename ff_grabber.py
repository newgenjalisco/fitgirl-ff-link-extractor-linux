import setuptools  # Register distutils fallback
import os
import traceback
import datetime

# --- TEMP DIAGNOSTICS (remove after debugging) ---
DIAG_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diagnostics.log")

def diag(msg, exc=False):
    line = f"[{datetime.datetime.now():%H:%M:%S}] {msg}"
    if exc:
        line += "\n" + traceback.format_exc()
    print(line, flush=True)
    try:
        with open(DIAG_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
# --------------------------------------------------
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import queue
import time
import re
import requests
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

class FitgirlExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FitGirl FF Link Extractor (Pro)")
        self.root.geometry("700x750")
        self.root.minsize(550, 600)
        
        # Configure layout weighting
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1) # Checklist area
        self.root.rowconfigure(5, weight=1) # Output area

        self.checkbox_vars = {}  # Store {url: BooleanVar}
        
        # --- Add this style configuration ---
        self.style = ttk.Style()
        self.style.theme_use("clam")  # Ensures color customization works
        self.style.configure(
            "Custom.Horizontal.TProgressbar",
            background="#24890d",   # Green color matching FitGirl's style
            troughcolor="#e0e0e0",  # Light grey empty background track
            bordercolor="#24890d",  # Matching border
            lightcolor="#24890d",
            darkcolor="#24890d"
        )
        # ------------------------------------

        self.setup_ui()

        # Thread-safe UI dispatch: worker threads must NEVER call Tk
        # methods directly (that can deadlock the interpreter and leave
        # the app stuck on "Fetching page..."). They enqueue callables
        # here; the main thread executes them via _poll_ui_queue.
        self._ui_queue = queue.Queue()
        self._fetch_token = 0
        self._fetch_active = False
        self._poll_ui_queue()

        # Bind MouseWheel globally
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)
        self.root.bind_all("<Button-4>", self._on_mousewheel) 
        self.root.bind_all("<Button-5>", self._on_mousewheel)

    def setup_ui(self):
        # 1. Input Frame
        input_frame = ttk.Frame(self.root, padding="10 10 10 5")
        input_frame.grid(row=0, column=0, sticky="ew")
        input_frame.columnconfigure(1, weight=1)

        ttk.Label(input_frame, text="FitGirl Game URL:", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="w", pady=5)
        
        self.url_var = tk.StringVar()
        self.url_var.set("https://fitgirl-repacks.site/grand-theft-auto-v/")
        self.url_entry = ttk.Entry(input_frame, textvariable=self.url_var, font=("Arial", 10))
        self.url_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=5)
        
        self.fetch_btn = ttk.Button(input_frame, text="1. Fetch Links", command=self.start_fetch_thread)
        self.fetch_btn.grid(row=2, column=0, columnspan=2, pady=5)

        # 2. Status Label
        self.status_var = tk.StringVar()
        self.status_var.set("Waiting for input...")
        status_label = ttk.Label(self.root, textvariable=self.status_var, font=("Arial", 9, "italic"), foreground="#555")
        status_label.grid(row=1, column=0, sticky="w", padx=10)

        # 3. Checklist Area (Scrollable)
        checklist_container = ttk.LabelFrame(self.root, text="Found Parts (Uncheck unwanted)", padding="5 5 5 5")
        checklist_container.grid(row=2, column=0, sticky="nsew", padx=10, pady=5)
        checklist_container.rowconfigure(0, weight=1)
        checklist_container.columnconfigure(0, weight=1)

        # Canvas & Scrollbar for Checklist
        self.canvas = tk.Canvas(checklist_container, highlightthickness=0)
        self.scrollbar_list = ttk.Scrollbar(checklist_container, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar_list.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar_list.grid(row=0, column=1, sticky="ns")

        # Checklist Controls
        controls_frame = ttk.Frame(checklist_container)
        controls_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        ttk.Button(controls_frame, text="Select All", command=self.select_all).pack(side="left", padx=2)
        ttk.Button(controls_frame, text="Deselect All", command=self.deselect_all).pack(side="left", padx=2)
        
        self.extract_btn = ttk.Button(controls_frame, text="2. Extract Selected", command=self.start_extraction_thread, state="disabled")
        self.extract_btn.pack(side="right", padx=2)
        self.browser_var = tk.StringVar(value="Auto-Detect Browser")
        self.browser_combo = ttk.Combobox(controls_frame, textvariable=self.browser_var, state="readonly", width=18)
        self.browser_combo['values'] = (
                    "Auto-Detect Browser", 
                    "Google Chrome", 
                    "Microsoft Edge", 
                    "Brave", 
                    "Mozilla Firefox"
                )
        self.browser_combo.pack(side="right", padx=(5, 10))

        # 4. Progress Bar
        self.progress = ttk.Progressbar(
            self.root, 
            orient="horizontal", 
            mode="determinate",
            style="Custom.Horizontal.TProgressbar"  # Apply our custom style here
        )
        self.progress.grid(row=4, column=0, sticky="ew", padx=10, pady=5)

        # 5. Output Links Frame
        output_frame = ttk.LabelFrame(self.root, text="Extracted Direct Links", padding="5 5 5 5")
        output_frame.grid(row=5, column=0, sticky="nsew", padx=10, pady=5)
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)

        self.text_area = tk.Text(output_frame, wrap="none", font=("Consolas", 9), height=10)
        self.text_area.grid(row=0, column=0, sticky="nsew")
        
        scrollbar_y = ttk.Scrollbar(output_frame, orient="vertical", command=self.text_area.yview)
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        self.text_area.configure(yscrollcommand=scrollbar_y.set)

        scrollbar_x = ttk.Scrollbar(output_frame, orient="horizontal", command=self.text_area.xview)
        scrollbar_x.grid(row=1, column=0, sticky="ew")
        self.text_area.configure(xscrollcommand=scrollbar_x.set)

        # 6. Bottom Buttons Frame
        btn_frame = ttk.Frame(self.root, padding="10 5 10 10")
        btn_frame.grid(row=6, column=0, sticky="ew")
        
        self.copy_btn = ttk.Button(btn_frame, text="📋 Copy All Links", command=self.copy_to_clipboard)
        self.copy_btn.pack(side="right")
        
        self.clear_btn = ttk.Button(btn_frame, text="Clear Output", command=self.clear_output)
        self.clear_btn.pack(side="right", padx=10)


    # --- Mousewheel Logic ---

    def _on_mousewheel(self, event):
        try:
            # Find exactly what widget the mouse is currently hovering over
            widget = self.root.winfo_containing(event.x_root, event.y_root)
            
            # If hovering over the canvas or any checkbox inside the scrollable frame
            if widget == self.canvas or (widget and str(widget).startswith(str(self.scrollable_frame))):
                if hasattr(event, 'delta') and event.delta != 0:
                    # Windows / macOS
                    direction = -1 if event.delta > 0 else 1
                    self.canvas.yview_scroll(direction, "units")
                elif hasattr(event, 'num'):
                    # Linux
                    if event.num == 4:
                        self.canvas.yview_scroll(-1, "units")
                    elif event.num == 5:
                        self.canvas.yview_scroll(1, "units")
        except Exception:
            pass


    # --- UI Logic ---

    def select_all(self):
        for var in self.checkbox_vars.values():
            var.set(True)

    def deselect_all(self):
        for var in self.checkbox_vars.values():
            var.set(False)

    def copy_to_clipboard(self):
        links = self.text_area.get(1.0, tk.END).strip()
        if links:
            self.root.clipboard_clear()
            self.root.clipboard_append(links)
            messagebox.showinfo("Success", "All links copied to clipboard!")
        else:
            messagebox.showwarning("Empty", "No links to copy!")

    def clear_output(self):
        self.text_area.delete(1.0, tk.END)
        self.progress.config(value=0)

    def update_ui(self, status=None, progress_val=None, max_val=None, text_append=None):
        if status is not None:
            self.status_var.set(status)
        if max_val is not None:
            self.progress.config(maximum=max_val)
        if progress_val is not None:
            self.progress.config(value=progress_val)
        if text_append is not None:
            self.text_area.insert(tk.END, text_append + "\n")
            self.text_area.see(tk.END)


    # --- Step 1: Fetching Links ---

    # --- Thread-safe UI dispatch (main thread only executes these) ---

    def _ui_put(self, fn, *args):
        """Enqueue a UI callable from any thread. Never calls Tk directly."""
        self._ui_queue.put((fn, args))

    def _poll_ui_queue(self):
        try:
            while True:
                fn, args = self._ui_queue.get_nowait()
                try:
                    fn(*args)
                except Exception as e:
                    diag(f"UI CALLBACK ERROR: {e}", exc=True)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_ui_queue)

    def _fetch_watchdog(self, token):
        """Failsafe: if a fetch is still stuck after 45s (stalled
        connection, blocked site), unstick the UI and ignore the late
        thread when it eventually returns."""
        if self._fetch_active and token == self._fetch_token:
            diag("FETCH WATCHDOG: fetch still stuck after 45s, releasing UI")
            self._fetch_active = False
            self._fetch_token += 1  # invalidate the stuck thread's token
            self.status_var.set(
                "Fetch timed out: connection stalled or site blocking requests. "
                "Run from terminal to see details, or try a VPN/Custom DNS."
            )
            self.fetch_btn.config(state="normal")

    def _fetch_done(self, token):
        if token == self._fetch_token:
            self._fetch_active = False
            self.fetch_btn.config(state="normal")

    def populate_checkboxes_token(self, token, links):
        if token != self._fetch_token:
            return  # stale result from a timed-out fetch; ignore
        self.populate_checkboxes(links)


    # --- Step 1: Fetching Links ---

    def start_fetch_thread(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a valid FitGirl URL.")
            return

        self._fetch_token += 1
        token = self._fetch_token
        self._fetch_active = True
        self.fetch_btn.config(state="disabled")
        self.extract_btn.config(state="disabled")
        self.status_var.set("Fetching page...")
        
        # Clear existing checkboxes
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.checkbox_vars.clear()

        thread = threading.Thread(target=self.run_fetch, args=(url, token), daemon=True)
        thread.start()
        # Failsafe so the UI can never stick on "Fetching page..." forever
        self.root.after(45000, lambda: self._fetch_watchdog(token))

    def run_fetch(self, url, token):
        """Worker thread: must never touch Tk directly, only via _ui_put.
        Uses streaming + an overall byte/time budget so a trickling or
        stalled connection cannot hang forever (requests' timeout is
        per-read and resets on every byte received)."""
        diag(f"FETCH START: {url}")
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/126.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            html = None
            last_err = None
            for attempt in (1, 2):
                if token != self._fetch_token:
                    diag("FETCH ABORT: superseded by newer fetch")
                    return
                try:
                    diag(f"FETCH attempt {attempt}...")
                    t0 = time.monotonic()
                    with requests.Session() as s:
                        with s.get(url, headers=headers,
                                   timeout=(10, 15), stream=True) as res:
                            res.raise_for_status()
                            chunks = []
                            total = 0
                            for chunk in res.iter_content(chunk_size=65536):
                                if token != self._fetch_token:
                                    diag("FETCH ABORT: superseded mid-download")
                                    return
                                if chunk:
                                    chunks.append(chunk)
                                    total += len(chunk)
                                # Overall budget: 30s / 15MB max. This catches
                                # stalled/trickling connections that per-read
                                # timeouts alone cannot.
                                if time.monotonic() - t0 > 30:
                                    raise TimeoutError(
                                        "download stalled (30s budget exceeded) - "
                                        "connection is trickling or hanging")
                                if total > 15_000_000:
                                    break
                            html = b"".join(chunks).decode(
                                res.encoding or "utf-8", errors="replace")
                    diag(f"FETCH attempt {attempt}: got {len(html)} chars "
                         f"in {time.monotonic()-t0:.1f}s")
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    diag(f"FETCH attempt {attempt} failed: "
                         f"{type(e).__name__}: {e}", exc=True)
                    time.sleep(2)

            if token != self._fetch_token:
                return
            if html is None:
                if isinstance(last_err, requests.exceptions.ConnectionError):
                    msg = ("Network Error: Cannot reach FitGirl. "
                           "Is your ISP blocking it? Try a VPN/Custom DNS. "
                           f"({last_err})")
                elif isinstance(last_err, TimeoutError):
                    msg = (f"Fetch stalled: {last_err} "
                           "Try again or use a VPN/Custom DNS.")
                else:
                    msg = (f"Error fetching links: "
                           f"{type(last_err).__name__}: {last_err}")
                self._ui_put(self.update_ui, msg)
                return

            soup = BeautifulSoup(html, 'html.parser')
            ff_links = []
            for a in soup.find_all('a', href=True):
                if 'fuckingfast.co' in a['href'] and a['href'] not in ff_links:
                    ff_links.append(a['href'])
            diag(f"FETCH DONE: found {len(ff_links)} fuckingfast links")

            if not ff_links:
                low = html.lower()
                if ('just a moment' in low or 'challenge-platform' in low
                        or 'cf_chl' in low):
                    self._ui_put(self.update_ui,
                        "Page loaded but shows a bot-check (Cloudflare). "
                        "requests can't pass it: try a VPN, or paste a "
                        "different FitGirl mirror URL.")
                else:
                    self._ui_put(self.populate_checkboxes_token, token, [])
                return
            self._ui_put(self.populate_checkboxes_token, token, ff_links)

        except Exception as e:
            diag(f"FETCH ERROR: {e}", exc=True)
            self._ui_put(self.update_ui, f"Error fetching links: {str(e)}")
        finally:
            self._ui_put(self._fetch_done, token)

    def populate_checkboxes(self, links):
        if not links:
            self.status_var.set("No FuckingFast links found on this page!")
            self.fetch_btn.config(state="normal")
            return

        for link in links:
            var = tk.BooleanVar(value=True)
            self.checkbox_vars[link] = var
            
            # Extract readable name
            filename = link.split('#')[-1] if '#' in link else link.split('/')[-1]
            
            chk = ttk.Checkbutton(self.scrollable_frame, text=filename, variable=var)
            chk.pack(anchor="w", padx=5, pady=2)

        self.status_var.set(f"Found {len(links)} parts. Select what you need and click Extract.")
        self.fetch_btn.config(state="normal")
        self.extract_btn.config(state="normal")


    # --- Step 2: Extraction ---
    def get_browser_path(self, selected_browser="Auto-Detect Browser"):
        import sys
        import shutil
        
        # Check if running on Linux / Steam Deck
        is_linux = sys.platform.startswith('linux')
        
        browser_paths = {
            "Google Chrome": [
                r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
                r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
                r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/var/lib/flatpak/exports/bin/com.google.Chrome" # Common Steam Deck Flatpak path
            ],
            "Microsoft Edge": [
                r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
                r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
                r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe",
                "/usr/bin/microsoft-edge-stable",
                "/usr/bin/microsoft-edge"
            ],
            "Brave": [
                r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe",
                "/usr/bin/brave-browser",
                "/usr/bin/brave",
                "/usr/bin/brave-browser-stable",
                # brave-origin naming (Fedora / custom installs)
                "/usr/bin/brave-origin",
                "/usr/bin/brave-origin-stable",
                "/etc/alternatives/brave-origin",
                "/opt/brave.com/brave-origin/brave-origin",
                "/opt/brave.com/Brave-Origin/brave-origin",
                "/var/lib/flatpak/exports/bin/com.brave.Browser" # Common Steam Deck Flatpak path
            ],
            "Mozilla Firefox": [
                r"%ProgramFiles%\Mozilla Firefox\firefox.exe",
                r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe",
                r"%LocalAppData%\Mozilla Firefox\firefox.exe",
                "/usr/bin/firefox",
                "/var/lib/flatpak/exports/bin/org.mozilla.firefox"
            ]
        }
        # PATH-based binaries to check via shutil.which (handles brave-origin, etc.)
        browser_which_names = {
            "Google Chrome": ["google-chrome", "google-chrome-stable"],
            "Microsoft Edge": ["microsoft-edge", "microsoft-edge-stable", "msedge"],
            "Brave": ["brave-browser", "brave-browser-stable", "brave", "brave-origin", "brave-origin-stable"],
            "Mozilla Firefox": ["firefox"],
        }
        
        if selected_browser != "Auto-Detect Browser":
            paths_to_check = browser_paths.get(selected_browser, [])
        else:
            paths_to_check = []
            for paths in browser_paths.values():
                paths_to_check.extend(paths)

        for path in paths_to_check:
            # os.path.expandvars handles the Windows % variables, safely ignores Linux ones
            expanded_path = os.path.expandvars(path)
            if os.path.exists(expanded_path):
                return expanded_path

        # Fallback: search PATH (covers /usr/bin symlinks like brave-origin)
        if selected_browser != "Auto-Detect Browser":
            names_to_check = browser_which_names.get(selected_browser, [])
        else:
            names_to_check = []
            for names in browser_which_names.values():
                names_to_check.extend(names)
        for name in names_to_check:
            found = shutil.which(name)
            if found and os.path.exists(found):
                return found
        return None
    

    def start_extraction_thread(self):
        selected_links = [url for url, var in self.checkbox_vars.items() if var.get()]
        
        if not selected_links:
            messagebox.showwarning("Warning", "No links selected to extract!")
            return

        self.fetch_btn.config(state="disabled")
        self.extract_btn.config(state="disabled")
        self.clear_output()

        thread = threading.Thread(target=self.run_extraction, args=(selected_links,), daemon=True)
        thread.start()

    def run_extraction(self, links):
        driver = None
        total = len(links)
        
        selected_browser = self.browser_var.get()
        browser_executable = self.get_browser_path(selected_browser)
        
        if not browser_executable:
            self._ui_put(self.update_ui, f"Error: Could not find {selected_browser} on your system.")
            self._ui_put(lambda: self.fetch_btn.config(state="normal"))
            self._ui_put(lambda: self.extract_btn.config(state="normal"))
            return

        browser_name = os.path.basename(browser_executable).replace('.exe', '')
        diag(f"EXTRACTION START: {total} links, browser={selected_browser} -> {browser_executable}")
        self._ui_put(self.update_ui, f"Initializing using {browser_name} to bypass Cloudflare...", 0, total)
        
        def create_driver(version=None):
            if browser_name.lower() == 'firefox':
                from selenium import webdriver
                from selenium.webdriver.firefox.options import Options
                opts = Options()
                opts.binary_location = browser_executable
                # geckodriver exposes navigator.webdriver regardless of these
                # preferences, so Cloudflare can still detect the session
                opts.set_preference("dom.webdriver.enabled", False)
                return webdriver.Firefox(options=opts)
            elif browser_name.lower() == 'msedge':
                from selenium import webdriver
                from selenium.webdriver.edge.options import Options
                opts = Options()
                opts.binary_location = browser_executable
                opts.add_experimental_option("excludeSwitches", ["enable-automation"])
                opts.add_experimental_option('useAutomationExtension', False)
                opts.add_argument("--disable-blink-features=AutomationControlled")
                return webdriver.Edge(options=opts)
            else:
                opts = uc.ChromeOptions()
                return uc.Chrome(
                    options=opts, 
                    use_subprocess=True, 
                    browser_executable_path=browser_executable, 
                    version_main=version
                )
        
        def ensure_window(drv):
            # Reattach to a surviving window and keep a spare blank tab open,
            # so a site closing its own window can't take the whole browser down
            handles = drv.window_handles
            if not handles:
                raise RuntimeError("all browser windows closed")
            try:
                drv.current_window_handle
            except Exception:
                drv.switch_to.window(handles[-1])
            if len(drv.window_handles) < 2:
                try:
                    drv.execute_script("window.open('about:blank','_blank');")
                except Exception:
                    pass

        def session_is_dead(err):
            msg = str(err)
            return any(s in msg for s in (
                "invalid session id",
                "browser has closed",
                "not connected to DevTools",
                "no such window",
                "web view not found",
                "chrome not reachable",
                "unable to connect to renderer",
                "Tried to run command without establishing a connection",
                "Browsing context has been discarded",
                "Failed to decode response from marionette",
            ))

        working_version = None
        try:
            try:
                driver = create_driver()
            except Exception as e:
                diag(f"DRIVER CREATE ERROR ({browser_name}): {e}", exc=True)
                error_msg = str(e)
                if browser_name.lower() not in ['firefox', 'msedge'] and "Current browser version is" in error_msg:
                    match = re.search(r"Current browser version is (\d+)", error_msg)
                    if match:
                        correct_version = int(match.group(1))
                        working_version = correct_version
                        self._ui_put(self.update_ui, f"Auto-fixing ChromeDriver version to v{correct_version}...")
                        driver = create_driver(version=correct_version)
                    else:
                        raise e
                else:
                    raise e

            # --- Block downloads globally so Chrome doesn't actually download the 5GB files ---
            if browser_name.lower() != 'firefox':
                try:
                    # (Removed the local 'import os' that was causing the crash!)
                    driver.execute_cdp_cmd(
                        "Browser.setDownloadBehavior", {
                            "behavior": "deny",
                            "downloadPath": os.path.abspath(os.sep)
                        }
                    )
                except:
                    pass
            # ---------------------------------------------------------------------------------

            # --- Javascript Interceptors ---
            js_inject = """
            // 1. Kill popup ads instantly
            window.open = function() { return null; };
            
            // 2. Intercept the network request to catch the direct URL before HTMX processes it
            if (!window.xhrIntercepted) {
                window.xhrIntercepted = true;
                var originalXHR = window.XMLHttpRequest;
                window.XMLHttpRequest = function() {
                    var xhr = new originalXHR();
                    xhr.addEventListener('readystatechange', function() {
                        if (xhr.readyState === 4) {
                            var redirect = xhr.getResponseHeader('hx-redirect') || xhr.getResponseHeader('location');
                            if (redirect && redirect.includes('dl.fuckingfast.co')) {
                                document.body.setAttribute('data-direct-url', redirect);
                            }
                        }
                    });
                    return xhr;
                };
            }
            """
            
            js_click = """
            let btn = document.querySelector('a[hx-post]');
            if (btn && btn.style.opacity !== '0.5') {
                btn.click(); // Natively click the button!
            }
            return document.body.getAttribute('data-direct-url');
            """
            # -------------------------------

            for i, link in enumerate(links, 1):
                filename = link.split('#')[-1] if '#' in link else link.split('/')[-1]
                self._ui_put(self.update_ui, f"Processing [{i}/{total}]: {filename}")
                
                try:
                    driver.get(link)
                    driver.execute_script(js_inject)
                    
                    direct_url = None
                    for _ in range(30):
                        time.sleep(1)
                        
                        # Click the button and check if our interceptor caught the URL
                        result = driver.execute_script(js_click)
                        if result and "dl.fuckingfast.co" in result:
                            direct_url = result
                            break
                            
                        # Fallback: check if the browser natively navigated to the link
                        if "dl.fuckingfast.co" in driver.current_url:
                            direct_url = driver.current_url
                            break
                            
                        # Fallback: Old window.open method
                        match_old = re.search(r'window\.open\("([^"]+)"\)', driver.page_source)
                        if match_old:
                            direct_url = match_old.group(1)
                            break
                            
                    if direct_url:
                        self._ui_put(self.update_ui, None, i, None, direct_url)
                    else:
                        self._ui_put(self.update_ui, None, i, None, f"# FAILED: {filename} ({link})")
                        
                except Exception as e:
                    self._ui_put(self.update_ui, None, i, None, f"# ERROR: {str(e)} -> {filename}")

            else:
                self._ui_put(self.update_ui, f"Extraction complete! Processed {total} links.")
            
        except Exception as e:
            diag(f"CRITICAL ERROR: {e}", exc=True)
            self._ui_put(self.update_ui, f"Critical Error: {str(e)}")
            
        finally:
            self._ui_put(lambda: self.fetch_btn.config(state="normal"))
            self._ui_put(lambda: self.extract_btn.config(state="normal"))
            if driver:
                try:
                    driver.quit()
                except:
                    pass

if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
        
    app = FitgirlExtractorApp(root)
    root.mainloop()
