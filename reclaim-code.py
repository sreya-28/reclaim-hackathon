import time
import threading
from pynput import keyboard, mouse
import pyttsx3
import speech_recognition as sr
import tkinter as tk
from tkinter import messagebox
import cv2
import winsound  # For beep alerts on Windows

# ================= CONFIG =================
INACTIVITY_LIMIT = 5       # keyboard/mouse inactivity (seconds)
NO_FACE_LIMIT = 3          # seconds without face detected (faster alert)
NO_GAZE_LIMIT = 5          # seconds of not looking at screen (zone out detection)
NO_FACE_CRITICAL = 10      # seconds - critical threshold (sudden alert)
NO_ACTIVITY_CRITICAL = 10  # seconds - critical threshold (sudden alert)
ALERT_TRIGGER_TIME = 10    # generate alert within 10 seconds
REFOCUS_COUNTDOWN = 10     # seconds to refocus after alert
DEBUG_MODE = True         # Set to True to see detailed logging
# =========================================

# ================= ALERT MESSAGES =================
ALERT_MESSAGES = {
    'no_face': {
        'title': '👁️ FACE NOT DETECTED',
        'reason': 'Your face is not visible. Are you looking away from the screen?\nPlease stay engaged with your task.',
        'voice': 'Alert! Face not detected. Please look at your screen and stay focused on your task.',
    },
    'not_looking': {
        'title': '👀 ZONE OUT DETECTED',
        'reason': 'You are not looking at the screen!\nYour eyes are looking away. Please refocus on your task.',
        'voice': 'Zone out detected! You are not looking at the screen. Please look back and focus on your task.',
    },
    'no_activity': {
        'title': '⌨️ NO ACTIVITY DETECTED',
        'reason': 'No keyboard or mouse activity detected.\nAre you stuck or distracted? Please continue working.',
        'voice': 'Alert! No activity detected. Please continue working on your task.',
    },
    'critical': {
        'title': '🚨 CRITICAL DISENGAGEMENT',
        'reason': f'SUDDEN ALERT!\nEither:\n• No face detected for 10+ seconds, OR\n• No activity for 10+ seconds\n\nYou are DISENGAGED. REFOCUS IMMEDIATELY!',
        'voice': 'CRITICAL ALERT! You are disengaged from your task. Either your face is not detected or you have not performed any activity for 10 seconds. Refocus immediately!',
    },
    'both': {
        'title': '🚨 FOCUS LOST - BOTH CONDITIONS',
        'reason': 'Face not detected AND no activity detected!\nYou seem completely disengaged. Refocus now!',
        'voice': 'Critical alert! Face not detected and no activity. You are completely disengaged. Focus on your task immediately!',
    }
}
# =========================================

# ================= STATE =================
last_activity_time = time.time()
last_face_time = time.time()
last_gaze_time = time.time()  # Track when user last looked at screen
last_alert_time = time.time()  # Track last alert to prevent spam
popup_active = threading.Event()  # prevents multiple popups at once
camera_working = False  # Track if camera is properly initialized
alert_timer_start = None  # Track when alert-triggering condition started
critical_alert_triggered = False  # Track if critical alert already fired
current_alert_reason = None  # What triggered the alert
ALERT_COOLDOWN = 15  # seconds between regular alerts (prevent spam)
last_critical_satisfied_time = 0  # Track when critical condition was last satisfied
critical_condition_was_active = False  # Track if condition was previously active (for single alert)
# =========================================

# ================= VOICE & AUDIO =================
engine = pyttsx3.init()
engine.setProperty('rate', 140)  # Slower speech for clarity
engine.setProperty('volume', 1.0)  # Max volume

def beep_alert():
    """Play beep alert for attention"""
    try:
        for _ in range(3):
            winsound.Beep(1000, 200)  # Frequency: 1000Hz, Duration: 200ms
            time.sleep(0.2)
        print("✅ Beep alert played")
    except Exception as e:
        print(f"❌ Beep error: {e}")

def speak(text):
    """Text-to-speech alert (blocking, so use in threads)"""
    try:
        print(f"🎤 Speaking: {text}")
        engine.say(text)
        engine.runAndWait()
        print(f"✅ Voice alert completed")
    except Exception as e:
        print(f"❌ Voice error: {e}")

def listen_command(timeout=10):
    """Listen for voice commands with improved settings and 10-second timeout"""
    recognizer = sr.Recognizer()
    
    # Adjust recognizer sensitivity for better detection
    recognizer.dynamic_energy_threshold = True
    recognizer.energy_threshold = 4000  # Lower threshold to catch quieter speech
    
    try:
        with sr.Microphone() as source:
            print(f"🎤 Calibrating microphone...")
            # Longer calibration for better noise detection
            recognizer.adjust_for_ambient_noise(source, duration=2)
            print(f"🎤 Listening for voice command ({timeout}s timeout)...")
            print(f"   💬 Speak clearly: 'I'm focused', 'I'm back', 'ok', 'yes'")
            
            # Listen with more flexibility
            audio = recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=timeout,
                max_listening_duration=timeout
            )
        
        print(f"✅ Audio captured ({len(audio.frame_data)} bytes)")
        
        # Try Google Speech Recognition
        try:
            command = recognizer.recognize_google(audio, language='en-US')
            print(f"✅ Recognized: '{command}'")
            return command.lower()
        except sr.UnknownValueError:
            print(f"❌ Audio captured but unclear. Try speaking louder or clearer.")
            return ""
        
    except sr.RequestError as e:
        print(f"❌ Google API error: {e}")
        print(f"   Check internet connection")
        return ""
    except sr.UnknownValueError:
        print("❌ Could not understand audio")
        return ""
    except sr.MicrophoneUnavailableError:
        print("❌ Microphone not available")
        return ""
    except Exception as e:
        print(f"❌ Listening error: {e}")
        return ""

# ================= GUI POPUP =================
def focus_popup(alert_type='both', reason=None):
    """Run popup in a separate thread to avoid blocking monitor loop"""
    
    def show_popup():
        # Get message based on alert type
        alert_data = ALERT_MESSAGES.get(alert_type, ALERT_MESSAGES['both'])
        voice_msg = alert_data['voice']
        title_text = alert_data['title']
        reason_text = reason or alert_data['reason']
        
        print(f"[POPUP] Starting alert popup: {alert_type}")
        
        # Play beep first
        beep_thread = threading.Thread(target=beep_alert, daemon=True)
        beep_thread.start()
        time.sleep(0.3)  # Wait for beep to start
        
        # Speak the message (blocking call)
        try:
            speak(voice_msg)
        except Exception as e:
            print(f"Voice playback error: {e}")
        
        try:
            # Show GUI
            root = tk.Tk()
            root.title("⚠️ RECLAIM ALERT")
            root.geometry("500x420")  # Larger popup
            root.resizable(False, False)
            root.attributes('-topmost', True)  # Bring to front
            root.attributes('-alpha', 0.95)   # Slightly transparent
            
            # Set background color to red for visibility
            root.config(bg="#ffebee")

            # Main title
            title_frame = tk.Frame(root, bg="#d32f2f")
            title_frame.pack(fill=tk.X, padx=0, pady=0)
            
            tk.Label(
                title_frame,
                text=f"🚨 RECLAIM ALERT 🚨",
                font=("Arial", 14, "bold"),
                fg="white",
                bg="#d32f2f"
            ).pack(pady=10)

            # Alert type title
            tk.Label(
                root,
                text=title_text,
                font=("Arial", 12, "bold"),
                fg="#c62828",
                bg="#ffebee"
            ).pack(pady=8)

            # Reason
            tk.Label(
                root,
                text=reason_text,
                font=("Arial", 11),
                wraplength=450,
                fg="#1565c0",
                bg="#ffebee"
            ).pack(pady=10)

            # Voice status label
            voice_status = tk.Label(
                root,
                text="🎤 Say 'I'm focused' or 'I'm back'",
                font=("Arial", 10, "bold"),
                fg="#1565c0",
                bg="#ffebee"
            )
            voice_status.pack(pady=8)

            # Recognition feedback label
            feedback_label = tk.Label(
                root,
                text="",
                font=("Arial", 9),
                fg="green",
                bg="#ffebee"
            )
            feedback_label.pack(pady=3)

            # Large countdown timer
            timer_label = tk.Label(
                root,
                text=f"⏱️  {REFOCUS_COUNTDOWN}s",
                font=("Arial", 48, "bold"),
                fg="#d32f2f",
                bg="#ffebee"
            )
            timer_label.pack(pady=12)

            # Tips based on alert type
            if alert_type == 'no_face':
                tip_text = "💡 Turn back to your screen and stay visible to the camera"
            elif alert_type == 'no_activity':
                tip_text = "💡 Keep working! Move your mouse or press keys to stay active"
            elif alert_type == 'not_looking':
                tip_text = "💡 Look back at the screen and continue your task"
            else:
                tip_text = "💡 Get back on task NOW!"
            
            tk.Label(
                root,
                text=tip_text,
                font=("Arial", 10),
                fg="#1976d2",
                bg="#ffebee"
            ).pack(pady=5)

            # Button frame
            button_frame = tk.Frame(root, bg="#ffebee")
            button_frame.pack(pady=10)

            def dismiss():
                try:
                    if root.winfo_exists():
                        root.destroy()
                        print(f"[POPUP] Alert dismissed")
                except:
                    pass

            # Buttons for manual response
            focused_btn = tk.Button(
                button_frame,
                text="I'm Focused",
                command=dismiss,
                width=12,
                bg="#4CAF50",
                fg="white",
                font=("Arial", 10, "bold")
            )
            focused_btn.pack(side=tk.LEFT, padx=5)

            dismiss_btn = tk.Button(
                button_frame,
                text="I'm Back",
                command=dismiss,
                width=12,
                bg="#2196F3",
                fg="white",
                font=("Arial", 10, "bold")
            )
            dismiss_btn.pack(side=tk.LEFT, padx=5)

            # Voice listening function
            def voice_listener():
                try:
                    if not root.winfo_exists():
                        return
                    
                    voice_status.config(text="🎤 Listening for 10 seconds...")
                    root.update()  # Force GUI update before blocking
                except:
                    return
                
                try:
                    speak("Please respond: Say I'm focused or I'm back to dismiss this alert")
                except:
                    pass
                
                command = listen_command(timeout=10)
                
                # Only update GUI if window still exists
                if not root.winfo_exists():
                    return
                
                try:
                    if command:
                        feedback_label.config(text=f"Heard: '{command}'", fg="green")
                        root.update()
                        
                        # Check for recognition keywords
                        if any(word in command for word in ['focused', 'back', 'resume', 'ok', 'okay', 'yes', 'i am', "i'm"]):
                            try:
                                speak("Good! Keep your focus on the task.")
                            except:
                                pass
                            dismiss()
                        else:
                            feedback_label.config(text="Not recognized. Click button or try again.", fg="orange")
                            voice_status.config(text="🎤 Try again or use button")
                            root.update()
                    else:
                        feedback_label.config(text="No voice detected. Using button instead.", fg="gray")
                        voice_status.config(text="Click button to dismiss")
                        root.update()
                except RuntimeError:
                    # Window was destroyed, exit gracefully
                    pass
                except Exception as e:
                    print(f"❌ Voice feedback error: {e}")

            # Start voice listener in background
            voice_thread = threading.Thread(target=voice_listener, daemon=True)
            voice_thread.start()

            def countdown(sec):
                try:
                    if not root.winfo_exists():
                        return
                    
                    if sec >= 0:
                        timer_label.config(text=f"⏱️  {sec}s")
                        root.after(1000, countdown, sec - 1)
                    else:
                        dismiss()
                except (RuntimeError, tk.TclError):
                    # Window was destroyed
                    pass

            countdown(REFOCUS_COUNTDOWN)
            
            print(f"[POPUP] Alert window displayed")
            root.mainloop()
            print(f"[POPUP] Alert window closed")
        
        except Exception as e:
            print(f"❌ Popup error: {e}")

    # Run popup in separate thread so monitor loop keeps running
    popup_thread = threading.Thread(target=show_popup, daemon=True)
    popup_thread.start()
    print(f"[POPUP] Thread started for alert: {alert_type}")

# ================= ACTIVITY TRACKING =================
def update_activity():
    global last_activity_time
    last_activity_time = time.time()

def on_key_press(key):
    update_activity()

def on_mouse_move(x, y):
    update_activity()

def on_mouse_click(x, y, button, pressed):
    update_activity()

# ================= CAMERA MONITOR =================
camera_display_active = False

def camera_monitor():
    global last_face_time, camera_working, camera_display_active, last_gaze_time

    try:
        cap = cv2.VideoCapture(0)
        
        # Set backend to ensure compatibility
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Reduce buffer to prevent lag
        
        if not cap.isOpened():
            print("❌ Camera access denied or unavailable")
            print("   💡 Try: Checking if camera is already in use by another app")
            print("   💡 Try: Restarting the application")
            print("   💡 Try: Checking camera permissions")
            camera_working = False
            return

        print("📷 Camera access granted")
        print("🪟 Camera feed window opening... (press 'q' to close)")
        camera_working = True
        
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        eye_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_eye.xml"
        )
        
        # Set camera resolution for better performance
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)

        camera_display_active = True
        
        while camera_display_active:
            try:
                ret, frame = cap.read()
                if not ret:
                    print("⚠️  Camera frame read failed")
                    print("   💡 This is normal if camera is in use elsewhere")
                    print("   💡 System will continue monitoring activity only")
                    camera_working = False
                    break

                # Flip frame for mirror effect (more natural)
                frame = cv2.flip(frame, 1)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=4,
                    minSize=(20, 20)
                )

                # Draw face detection rectangles
                face_detected = len(faces) > 0
                eyes_detected = False
                
                for (x, y, w, h) in faces:
                    # Green rectangle for detected face
                    cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                    # Label with "FACE DETECTED"
                    cv2.putText(frame, "FACE DETECTED", (x, y-10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    
                    # Detect eyes within face region
                    roi_gray = gray[y:y+h, x:x+w]
                    roi_color = frame[y:y+h, x:x+w]
                    eyes = eye_cascade.detectMultiScale(roi_gray, 1.1, 4)
                    
                    if len(eyes) >= 2:  # Both eyes detected = looking forward
                        eyes_detected = True
                        last_gaze_time = time.time()
                        
                        # Draw green circles for eyes
                        for (ex, ey, ew, eh) in eyes[:2]:
                            cv2.circle(roi_color, (ex+ew//2, ey+eh//2), 5, (0, 255, 0), 2)
                        cv2.putText(roi_color, "LOOKING", (10, 30),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    else:
                        # Eyes not clearly visible = looking away
                        cv2.putText(roi_color, "LOOKING AWAY", (10, 30),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

                # Add status information
                status_text = "✅ FACE DETECTED" if face_detected else "❌ NO FACE"
                gaze_text = f"👀 {'Looking At Screen' if eyes_detected else 'Looking Away'}" if face_detected else ""
                status_color = (0, 255, 0) if face_detected else (0, 0, 255)
                gaze_color = (0, 255, 0) if eyes_detected else (0, 0, 255)
                
                cv2.putText(frame, status_text, (20, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, status_color, 2)
                
                if face_detected:
                    cv2.putText(frame, gaze_text, (20, 75),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, gaze_color, 2)
                
                # Add timing info
                now = time.time()
                no_face_time = now - last_face_time
                no_gaze_time = now - last_gaze_time
                inactivity = now - last_activity_time
                
                info_text = f"No Face: {no_face_time:.1f}s | Not Looking: {no_gaze_time:.1f}s | No Activity: {inactivity:.1f}s"
                cv2.putText(frame, info_text, (20, 460),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                
                cv2.putText(frame, "Press 'q' to close", (20, 475),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

                # Display frame
                cv2.imshow("📷 RECLAIM - Face & Gaze Recognition Monitor", frame)

                # Update face time if face is detected
                if face_detected:
                    last_face_time = time.time()

                # Check for 'q' key to close window
                if cv2.waitKey(30) & 0xFF == ord('q'):
                    print("🪟 Camera window closed by user")
                    break

                time.sleep(0.033)  # ~30 FPS
                
            except Exception as e:
                print(f"❌ Camera processing error: {e}")
                camera_working = False
                time.sleep(0.5)

        cv2.destroyAllWindows()
        cap.release()
        camera_display_active = False
        print("⚠️  Camera released")
        camera_working = False
        
    except Exception as e:
        print(f"❌ Camera monitor error: {e}")
        camera_display_active = False
        camera_working = False

# ================= FOCUS MONITOR =================
def focus_monitor():
    global last_activity_time, last_face_time, last_gaze_time, camera_working
    global last_alert_time, last_critical_satisfied_time, alert_timer_start
    global critical_condition_was_active

    last_logged_state = None  # Track last state to avoid spam
    
    while True:
        try:
            now = time.time()
            inactivity = now - last_activity_time
            no_face_time = now - last_face_time
            no_gaze_time = now - last_gaze_time
            time_since_alert = now - last_alert_time

            # DEBUG: Print current timings every 5 seconds
            if int(now) % 5 == 0:
                print(f"[MONITOR] Inactivity: {inactivity:.1f}s | No Face: {no_face_time:.1f}s | No Gaze: {no_gaze_time:.1f}s | Camera: {'✅ON' if camera_working else '❌OFF'}")

            # ===== CRITICAL ALERT CHECK (SINGLE POPUP) =====
            # Trigger ONLY ONCE when condition becomes satisfied
            no_face_critical = no_face_time >= NO_FACE_CRITICAL
            no_activity_critical = inactivity >= NO_ACTIVITY_CRITICAL
            
            critical_condition_met = no_face_critical or no_activity_critical
            
            # DEBUG: Show condition status every 5 seconds
            if int(now) % 5 == 0:
                print(f"[CRITICAL] No Face: {no_face_time:.1f}s >= {NO_FACE_CRITICAL}s? {no_face_critical} | No Activity: {inactivity:.1f}s >= {NO_ACTIVITY_CRITICAL}s? {no_activity_critical}")
                print(f"[CRITICAL] Condition Met: {critical_condition_met} | Was Active Before: {critical_condition_was_active}")
            
            # Fire alert ONLY when condition transitions from FALSE to TRUE
            if critical_condition_met and not critical_condition_was_active:
                # Condition just became active - FIRE ALERT ONCE
                trigger_reason = []
                if no_face_critical:
                    trigger_reason.append(f"No face: {no_face_time:.0f}s")
                if no_activity_critical:
                    trigger_reason.append(f"No activity: {inactivity:.0f}s")
                
                print(f"\n🚨🚨🚨 CRITICAL ALERT - FIRING ONCE 🚨🚨🚨")
                print(f"Condition: {' OR '.join(trigger_reason)}")
                print(f"   → POPUP TRIGGERED!\n")
                
                focus_popup(alert_type='critical')
                last_alert_time = time.time()
                last_critical_satisfied_time = now
                critical_condition_was_active = True
                
                time.sleep(0.5)
                continue
            
            # Update state: condition is still active but alert already fired
            if critical_condition_met:
                critical_condition_was_active = True
            else:
                # Condition resolved - reset for next alert
                if critical_condition_was_active:
                    print(f"✅ Critical condition RESOLVED - Ready for next alert\n")
                critical_condition_was_active = False
                last_critical_satisfied_time = 0

            # Check if enough time has passed since last regular alert
            if time_since_alert < ALERT_COOLDOWN:
                time.sleep(0.5)
                continue

            # Determine conditions
            face_visible = camera_working and no_face_time < NO_FACE_LIMIT
            gaze_forward = camera_working and no_gaze_time < NO_GAZE_LIMIT
            activity_okay = inactivity < INACTIVITY_LIMIT
            
            # Determine current state for logging (info only, no alerts)
            if face_visible and gaze_forward and activity_okay:
                current_state = 'focused'
            elif face_visible and gaze_forward:
                current_state = 'reading'
            elif face_visible and not gaze_forward:
                current_state = 'distracted'
            elif camera_working and no_face_time >= NO_FACE_LIMIT:
                current_state = 'no_face'
            elif camera_working and no_gaze_time >= NO_GAZE_LIMIT and face_visible:
                current_state = 'zone_out'
            else:
                current_state = 'unknown'
            
            # Log state changes (no alerts - only for info)
            if DEBUG_MODE or current_state != last_logged_state:
                if current_state == 'focused':
                    print(f"✅ FOCUSED: Face visible, looking at screen, active")
                elif current_state == 'reading':
                    print(f"✅ READING: Face visible, looking at screen, paused {inactivity:.0f}s")
                elif current_state == 'distracted':
                    print(f"⚠️  DISTRACTED: Face visible, looking away {no_gaze_time:.0f}s")
                elif current_state == 'no_face':
                    print(f"⚠️  NO FACE: Not visible for {no_face_time:.0f}s (⚠️  CRITICAL at {NO_FACE_CRITICAL}s)")
                elif current_state == 'zone_out':
                    print(f"⚠️  ZONE OUT: Not looking at screen for {no_gaze_time:.0f}s")
                else:
                    print(f"❓ UNKNOWN STATE")
                
                last_logged_state = current_state
            
            # NO MORE REGULAR ALERTS - ONLY CRITICAL ALERTS ABOVE TRIGGER THEM

            time.sleep(0.5)  # Check every 0.5 seconds for faster response

        except Exception as e:
            print(f"❌ Monitor error: {e}")
            time.sleep(0.5)

# ================= START SYSTEM =================
print("\n" + "="*60)
print("🧠 RECLAIM - Cognitive Engagement Monitor")
print("="*60)
print(f"⏱️  Inactivity Limit: {INACTIVITY_LIMIT}s")
print(f"👁️  Face Detection Limit: {NO_FACE_LIMIT}s")
print(f"👀 Zone Out (Not Looking) Limit: {NO_GAZE_LIMIT}s")
print(f"⏳ Alert Trigger Time: {ALERT_TRIGGER_TIME}s (alert generates within this time)")
print(f"🔄 Alert Cooldown: {ALERT_COOLDOWN}s")
print(f"\n🚨 CRITICAL ALERT (ONLY ALERT):")
print(f"   Alert ONLY when:")
print(f"   • No face > {NO_FACE_CRITICAL}s, OR")
print(f"   • No activity > {NO_ACTIVITY_CRITICAL}s")
print(f"   → INSTANT POPUP with VOICE MESSAGE")
print(f"\n🎤 Voice Alerts: Enabled (10s listening)")
print(f"� CAMERA: ENABLED - Face & Gaze Detection Active")
print(f"🐛 Debug Mode: {'ON' if DEBUG_MODE else 'OFF'}")
print("\n🎯 ALERT CONDITIONS:")
print(f"   🚨 No Face (>{NO_FACE_CRITICAL}s) → INSTANT ALERT")
print(f"   🚨 No Activity (>{NO_ACTIVITY_CRITICAL}s) → INSTANT ALERT")
print("\n⚠️  Press Ctrl+C to stop | Camera window: press 'q' to close\n")
print("="*60 + "\n")

# Test voice on startup
print("🔊 Testing voice system...")
try:
    speak("System started. Monitoring your focus.")
    print("✅ Voice system working!\n")
except Exception as e:
    print(f"⚠️  Voice test failed: {e}\n")

try:
    # Start activity listeners
    keyboard.Listener(on_press=on_key_press).start()
    mouse.Listener(on_move=on_mouse_move, on_click=on_mouse_click).start()
    print("✅ Activity listeners started")

    # Start camera monitor FIRST (so it initializes)
    print("🎥 Starting camera monitor...")
    camera_thread = threading.Thread(target=camera_monitor, daemon=True)
    camera_thread.start()
    time.sleep(2)  # Wait for camera to initialize
    print(f"✅ Camera monitor started (status: {'🟢 ACTIVE' if camera_working else '🔴 FAILED'})")

    # Start focus monitor
    threading.Thread(target=focus_monitor, daemon=True).start()
    print("✅ Focus monitor started\n")

    # Keep running
    while True:
        time.sleep(1)

except KeyboardInterrupt:
    print("\n\n🛑 System stopped.")
    try:
        speak("System stopped.")
    except:
        pass
