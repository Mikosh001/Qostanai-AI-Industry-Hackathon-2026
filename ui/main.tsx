import React, { useState, useEffect, useCallback, useRef } from "react";
import { createRoot } from "react-dom/client";
import {
  ShieldCheck,
  Monitor,
  Camera,
  Usb,
  Eye,
  Users,
  Activity,
  Settings,
  FileText,
  ChevronRight,
  Check,
  AlertTriangle,
  ArrowLeft,
  Play,
  Pause,
  Download,
  LogOut,
  Lock,
  Link2,
  RefreshCw,
  Trash2,
  GraduationCap,
  Search,
  CheckCircle2,
  XCircle,
  Clock,
  Server,
  Mic,
} from "lucide-react";
import "./styles.css";
import {
  t,
  getLocale,
  getLanguage,
  useLanguage,
  LanguageSelector,
} from "./i18n";

declare global {
  interface Window {
    sergek?: {
      invoke: (command: string, payload?: any) => Promise<any>;
      onLaunch: (listener: (payload: any) => void) => () => void;
    };
  }
}
const labels: Record<string, string> = {
  camera_pipeline_error: "Камера өңдеу қатесі",
  exam_renderer_crashed: "Емтихан терезесі тоқтады",
  evidence_write_failed: "Дәлелді сақтау орындалмады",
  remote_control: "Қашықтан басқару анықталды",
  remote_control_stopped: "Қашықтан басқару тоқтатылды",
  sound_activity: "Ұзақ дауыс белсенділігі",
  sustained_noise: "Ұзақ қатты шу анықталды",
  microphone_disconnected: "Микрофон ажыратылды",
  storage_enforcement_failed: "USB шектеуі орындалмады",
  identity_mismatch: "Бет бастапқы фотомен сәйкеспейді",
  presentation_attack: "Фото немесе экрандағы бейне күдігі",
  application_closed: "Бөгде бағдарлама жабылды",
  application_close_failed: "Бөгде бағдарламаны жабу расталмады",
  foreground_changed: "Белсенді бағдарлама өзгерді",
  remote_control_blocked: "Қашықтан басқару бұғатталды",
  remote_enforcement_failed: "Қашықтан басқару қорғанысы расталмады",
  screen_capture_error: "Экран жазбасы тоқтады",
  session_started: "Емтихан басталды",
  protected_desktop_left: "Windows қорғалған жұмыс ортасы ауысты",
  phone_detected: "Телефон анықталды",
  phone_raised: "Телефон экран алдына көтерілді",
  face_absent: "Бет көрінбейді",
  multiple_faces: "Екінші бет анықталды",
  gaze_down: "Төмен қарай ұзақ қарау",
  gaze_side: "Экраннан басқа жаққа қарау",
  camera_obscured: "Камера сапасы төмен",
  usb_connected: "Сыртқы жинақтауыш қосылды",
  usb_removed: "Жинақтауыш ажыратылды",
  shortcut_blocked: "Перне бұғатталды",
  focus_lost: "Терезе фокусы жоғалды",
  display_changed: "Монитор өзгерді",
  forbidden_process: "Рұқсатсыз қолданба",
  guard_lost: "Қорғаныс байланысы жоғалды",
  session_interrupted: "Сессия үзілді",
  navigation_blocked: "Сыртқы сілтеме бұғатталды",
  window_blocked: "Жаңа терезе бұғатталды",
  download_blocked: "Жүктеу бұғатталды",
  camera_disconnected: "Камера ажыратылды",
  emergency_release: "Апаттық шығу",
  peripheral_connected: "Жаңа құрылғы қосылды",
};
const statusLabels: Record<string, string> = {
  preflight: "Дайындық",
  active: "Белсенді",
  completed: "Аяқталды",
  interrupted: "Үзілді",
  pending: "Тексерілмеген",
  confirmed: "Расталды",
  dismissed: "Негізсіз",
};
const date = (value: string) =>
  new Date(value).toLocaleString(getLocale(), {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
async function api(path: string, method = "GET", body?: any) {
  const response = await fetch("/api" + path, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : JSON.stringify(error.detail),
    );
  }
  return response.json();
}
const invoke = (command: string, payload?: any) =>
  window.sergek
    ? window.sergek.invoke(command, payload)
    : Promise.reject(
        new Error("Студент емтиханы desktop қосымшасында ашылады."),
      );
function Badge({ value }: { value: string }) {
  return (
    <span className={"badge " + value}>{t(statusLabels[value] || value)}</span>
  );
}
function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark">
        <ShieldCheck size={25} />
      </span>
      <div>
        Sergек<span>PROCTOR</span>
      </div>
    </div>
  );
}
function ErrorBox({ error }: { error: string }) {
  return error ? (
    <div className="notice error" role="alert">
      <AlertTriangle size={18} />
      <span>{friendlyError(error)}</span>
    </div>
  ) : null;
}
function friendlyError(value: string) {
  if (!value) return value;
  value = value.replace(
    /^Error invoking remote method '[^']+':\s*(?:Error:\s*)?/,
    "",
  );
  const messages: [string, string][] = [
    [
      "requires administrator",
      "Әкімші рұқсаты қажет. Қосымшаны әкімші ретінде іске қосыңыз.",
    ],
    [
      "requires an administrator",
      "Әкімші рұқсаты қажет. Қосымшаны әкімші ретінде іске қосыңыз.",
    ],
    [
      "local Windows session",
      "Қатаң тест RDP арқылы ашылмайды. Компьютерге жергілікті кіріңіз.",
    ],
    ["No active session", "Сессия аяқталған. Басты бетке оралыңыз."],
    ["Session already exists", "Алдыңғы сессияны аяқтаңыз."],
    [
      "Keyboard hook unavailable",
      "Windows перне қорғанысы қосылмады. Қосымшаны қайта іске қосыңыз.",
    ],
    [
      "recovery pending",
      "Алдыңғы шектеулерді қалпына келтіру қажет. Әкімші ретінде қайта іске қосыңыз.",
    ],
    [
      "recovery is pending",
      "Алдыңғы шектеулерді қалпына келтіру қажет. Әкімші ретінде қайта іске қосыңыз.",
    ],
    [
      "Native guard unavailable",
      "Windows қорғаныс модулі ашылмады. Орнатқышты қайта орнатыңыз.",
    ],
  ];
  for (const [source, text] of messages)
    if (value.toLowerCase().includes(source.toLowerCase())) return t(text);
  try {
    const parsed = JSON.parse(value);
    if (parsed.errors)
      return parsed.errors.map((error: string) => t(error)).join(" · ");
  } catch {}
  return t(value);
}

function interruptionMessage(reason: string) {
  const messages: Record<string, string> = {
    application_close_failed:
      "Бөгде терезені жабу расталмады. Қорғаныс толық қосылмағандықтан емтихан тоқтатылды.",
    storage_enforcement_failed:
      "USB жинақтауышына қолжетімділік шектелмеді. Оқиға мұғалімге жіберілді.",
    guard_lost:
      "Windows қорғанысымен байланыс жоғалды. Компьютер шектеулері босатылды.",
    protected_desktop_left:
      "Windows жұмыс ортасы ауысты немесе компьютер бұғатталды.",
    emergency_release:
      "Апаттық шығу пернелері басылды. Компьютер шектеулері босатылды.",
    remote_enforcement_failed: "Қашықтан басқаруға тыйым салу расталмады.",
    backend_or_guard_connection_lost:
      "Бақылау қызметімен байланыс жоғалды. Қосымшаны қайта іске қосыңыз.",
    guard_process_exited: "Windows қорғаныс қызметі жабылды.",
    exam_open_failed:
      "Емтихан беті ашылмады. Moodle ортасының жұмысын тексеріңіз.",
  };
  return t(messages[reason] ||
    "Бақылау талаптарының бірі орындалмады. Нақты себеп оқиғалар журналында сақталды.");
}

function App() {
  useLanguage();
  const [teacher, setTeacher] = useState(
    new URLSearchParams(location.search).get("role") === "teacher",
  );
  const [health, setHealth] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api("/health")
      .then(setHealth)
      .catch((e) => setError(e.message));
  }, []);
  if (!health)
    return (
      <div className="loading">
        <Brand />
        <p>{error ? friendlyError(error) : t("Жүйе жүктелуде…")}</p>
      </div>
    );
  return teacher ? (
    <Teacher
      setup={health.setup_required}
      onStudent={() => setTeacher(false)}
      onSetup={() => setHealth({ ...health, setup_required: false })}
    />
  ) : (
    <Student
      onTeacher={() => setTeacher(true)}
      setupRequired={health.setup_required}
    />
  );
}

function Student({
  onTeacher,
  setupRequired,
}: {
  onTeacher: () => void;
  setupRequired: boolean;
}) {
  const [step, setStep] = useState("welcome");
  const [session, setSession] = useState<any>(null);
  const [snapshot, setSnapshot] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [startProgress, setStartProgress] = useState("");
  const [form, setForm] = useState({
    student: "",
    exam: "Бағдарламалау негіздері — таныстыру тесті",
    platform: "local",
    exam_url: "",
    camera_index: 0,
    launch_token: "",
    consent: false,
    mode: "strict",
  });
  const [demo, setDemo] = useState(false);
  const [portalAuthenticated, setPortalAuthenticated] = useState(false);
  const [cameraStream, setCameraStream] = useState("");
  const [guard, setGuard] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const [exam, setExam] = useState<any>(null);
  const [question, setQuestion] = useState(0);
  const [saved, setSaved] = useState("");
  const [seconds, setSeconds] = useState(1800);
  const desktop = !!window.sergek;
  const action = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (!window.sergek) return;
    const launch = async (token: string) => {
      try {
        const value = await invoke("resolve-launch", { token });
        setForm((f) => ({ ...f, ...value, launch_token: token }));
        setDemo(false);
        setStep("welcome");
        setError("");
      } catch (e: any) {
        setError(e.message);
      }
    };
    invoke("info").then((info) => {
      if (info.launch) launch(info.launch);
    });
    return window.sergek.onLaunch((value) => {
      if (typeof value.portalAuthenticated === "boolean")
        setPortalAuthenticated(value.portalAuthenticated);
      if (value.token) launch(value.token);
      if (value.portalError) {
        setStep("portal");
        setError(value.portalError);
      }
      if (typeof value.startProgress === "string")
        setStartProgress(value.startProgress);
      if (value.startError) {
        setStartProgress("");
        setError(value.startError);
        setStep("preflight");
      }
      if (value.exitRequested)
        setError(t("Емтиханды аяқтау немесе мұғалім рұқсатымен шығу қажет."));
    });
  }, []);
  useEffect(() => {
    if (
      !session ||
      step === "finished" ||
      session.data.policy.camera_required === false
    ) {
      setCameraStream("");
      return;
    }
    let alive = true;
    invoke("camera-stream")
      .then((value) => {
        if (alive) setCameraStream(value.url);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
      setCameraStream("");
    };
  }, [session?.id, step === "finished"]);
  useEffect(() => {
    if (!session || step === "finished") return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const value = await invoke("snapshot");
        if (!alive) return;
        setSnapshot(value);
        setGuard(value.guard);
        setSession(value.session);
        if (["completed", "interrupted"].includes(value.session.status)) {
          setResult(value.session);
          setStep("finished");
        }
      } catch (e: any) {
        if (alive) setError(e.message);
      } finally {
        if (alive) timer = setTimeout(tick, 700);
      }
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [session?.id, step]);
  useEffect(() => {
    if (step !== "exam" || !session || form.platform !== "local") return;
    const tick = () => {
      const started = session.data.active_started_at || session.created;
      setSeconds(
        Math.max(
          0,
          1800 - Math.floor((Date.now() - Date.parse(started)) / 1000),
        ),
      );
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [step, session]);
  useEffect(() => {
    if (step === "exam" && form.platform === "local" && seconds === 0) finish();
  }, [seconds]);
  async function create() {
    const item = await invoke("create", form);
    setSession(item);
    setStep("preflight");
  }
  async function start() {
    const item = await invoke("start");
    setSession(item);
    setStep("exam");
    if (item.data.platform === "local") {
      const value = await invoke("exam");
      setExam(value);
    }
  }
  async function finish() {
    await action(async () => {
      const item = await invoke("finish", {});
      setResult(item);
      setStep("finished");
    });
  }
  const signals = snapshot?.signals || {};
  const cameraRequired = session?.data?.policy?.camera_required !== false;
  if (step === "exam" && session?.data.platform !== "local")
    return (
      <>
        <div className="external-header">
          <LanguageSelector />
          <Brand />
          <span className="live-dot" /> <strong>{session.data.exam}</strong>
          <span className="muted">
            {session.status === "active"
              ? t("Қорғаныс пен жазба қосулы")
              : t("Moodle-де «Start attempt» басыңыз")}
          </span>
          {session.status === "active" &&
            signals.phone &&
            snapshot?.status?.last_analysis_age < 2 && (
              <span className="header-error">{t("Телефон байқалды")}</span>
            )}
          <span className="muted">
            {t(
              "Жауапты Moodle ішінде тапсырыңыз. Сессия автоматты аяқталады.",
            )}{" "}
          </span>
          {error && (
            <span className="header-error">{friendlyError(error)}</span>
          )}
        </div>
        {startProgress && (
          <div className="exam-loading" role="status">
            <ShieldCheck size={42} />
            <h2>{t(startProgress)}</h2>
            <p>{t("Тест дайын болғанда автоматты ашылады.")}</p>
          </div>
        )}
      </>
    );
  return (
    <div className="student-shell">
      <header className="student-header">
        <LanguageSelector />
        <Brand />
        <span className="muted">{t("Локалды емтихан қорғау жүйесі")}</span>
        {["welcome", "finished"].includes(step) && (
          <button className="btn text" onClick={onTeacher}>
            <GraduationCap size={18} />
            {t("Мұғалім панелі")}{" "}
          </button>
        )}
      </header>
      <main className="student-main">
        <ErrorBox error={error} />
        {step === "portal" && (
          <div className="portal-toolbar">
            {portalAuthenticated ? (
              <Brand />
            ) : (
              <strong>
                {t("Moodle: өз логиніңізбен кіріп, тестті таңдаңыз")}
              </strong>
            )}
            <button
              className="btn secondary"
              onClick={() =>
                action(async () => {
                  await invoke("close-portal");
                  setStep("welcome");
                })
              }
            >
              {t("Артқа")}{" "}
            </button>
          </div>
        )}
        {step === "welcome" && (
          <>
            <div className="student-intro">
              <span className="eyebrow">{t("ЕМТИХАНҒА СЕНІМДІ ДАЙЫНДЫҚ")}</span>
              <h1>
                {t("Біліміңізге назар аударыңыз.")} <br />
                <em>{t("Қорғанысты біз бақылаймыз.")}</em>
              </h1>
              <p>
                {t(
                  "Sergек камерадағы әрекеттерді, сыртқы құрылғыларды және емтихан ортасын бір сессияда бақылайды.",
                )}{" "}
              </p>
            </div>
            {!desktop && (
              <div className="notice">
                <Monitor size={20} />
                {t(
                  "Студент режимі орнатылған Windows қосымшасында жұмыс істейді. Бұл браузерден мұғалім панелін аша аласыз.",
                )}{" "}
              </div>
            )}
            {setupRequired && (
              <div className="notice">
                <Lock size={20} />
                {t(
                  "Алдымен мұғалім панелінде әкімшілік құпиясөзді орнатыңыз.",
                )}{" "}
              </div>
            )}
            <div className="welcome-grid">
              <section className="card form-card">
                <div className="section-title">
                  <span className="icon-tile">
                    <GraduationCap />
                  </span>
                  <div>
                    <h2>{t("Емтиханды бастау")}</h2>
                    <p>{t("Moodle → фото → емтихан")}</p>
                  </div>
                </div>
                {!form.launch_token && !demo ? (
                  <>
                    <p>
                      {t(
                        "Университеттің Moodle жүйесіне өз логиніңізбен кіріп, емтиханды таңдаңыз. Сілтемені енгізудің қажеті жоқ.",
                      )}{" "}
                    </p>
                    <button
                      className="btn primary wide"
                      disabled={busy || !desktop || setupRequired}
                      onClick={() =>
                        action(async () => {
                          setStep("portal");
                          try {
                            await invoke("open-portal");
                          } catch (e) {
                            setStep("welcome");
                            throw e;
                          }
                        })
                      }
                    >
                      {t("Moodle-ға кіру")} <ChevronRight size={18} />
                    </button>
                    <button
                      className="btn secondary wide"
                      disabled={!desktop || setupRequired}
                      onClick={() => setDemo(true)}
                    >
                      {t("Таныстыру тестін ашу")}{" "}
                    </button>
                  </>
                ) : (
                  <>
                    {demo ? (
                      <label>
                        {t("Аты-жөніңіз")}{" "}
                        <input
                          value={form.student}
                          onChange={(e) =>
                            setForm({ ...form, student: e.target.value })
                          }
                          placeholder={t("Аты-жөніңіз")}
                        />
                      </label>
                    ) : (
                      <div className="notice success">
                        <Check size={18} />
                        <span>
                          {t("Moodle-дан алынды:")}{" "}
                          <strong>{form.student}</strong>
                        </span>
                      </div>
                    )}
                    <div className="exam-selection">
                      <GraduationCap size={22} />
                      <div>
                        <small>{t("Таңдалған емтихан")}</small>
                        <h3>{demo ? t(form.exam) : form.exam}</h3>
                      </div>
                    </div>
                  </>
                )}
                {(demo || form.launch_token) && (
                  <>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={form.consent}
                        onChange={(e) =>
                          setForm({ ...form, consent: e.target.checked })
                        }
                      />
                      <span>
                        {t(
                          "Камераны, микрофонды, экранды, құрылғы оқиғаларын және бастапқы фотомен бет салыстыруды бақылауға, оқиға кезіндегі қысқа бейне және дыбыс үзінділерін сақтауға келісемін. Емтихан басталғанда басқа бағдарламалар автоматты жабылады; жұмысыңызды алдын ала сақтаңыз.",
                        )}{" "}
                      </span>
                    </label>
                    <button
                      className="btn primary wide"
                      disabled={
                        busy ||
                        !desktop ||
                        setupRequired ||
                        !form.consent ||
                        form.student.length < 2 ||
                        form.exam.length < 2
                      }
                      onClick={() => action(create)}
                    >
                      {t("Фотоға өту")} <ChevronRight size={18} />
                    </button>
                    <button
                      className="btn text wide"
                      onClick={() => {
                        setDemo(false);
                        setForm({ ...form, launch_token: "", consent: false });
                      }}
                    >
                      {t("Емтиханды қайта таңдау")}{" "}
                    </button>
                  </>
                )}
              </section>
              <aside className="welcome-aside">
                <div className="feature">
                  <Camera />
                  <div>
                    <h3>{t("Камера бақылауы")}</h3>
                    <p>{t("Телефон, бет саны және көзқарас бағыты.")}</p>
                  </div>
                </div>
                <div className="feature">
                  <Usb />
                  <div>
                    <h3>{t("Құрылғы бақылауы")}</h3>
                    <p>{t("Сыртқы жинақтауыш пен монитор өзгерістері.")}</p>
                  </div>
                </div>
                <div className="feature">
                  <ShieldCheck />
                  <div>
                    <h3>{t("Қорғалған орта")}</h3>
                    <p>
                      {t(
                        "Бөгде бағдарламаларды жабу, пернелер мен USB-ді шектеу — автоматты.",
                      )}{" "}
                    </p>
                  </div>
                </div>
                <div className="feature">
                  <Mic />
                  <div>
                    <h3>{t("Микрофон бақылауы")}</h3>
                    <p>
                      {t(
                        "Ұзақ дауыс пен қатты шу белгіленеді. Мұғалім дыбыс үзіндісін тыңдайды.",
                      )}{" "}
                    </p>
                  </div>
                </div>
                <div className="privacy-note">
                  <Lock size={18} />
                  <strong>{t("Бейне локалды өңделеді")}</strong>
                  <p>
                    {t(
                      "Оқиғаларды мұғалім тексереді. Автоматты айыптау немесе бағаны өзгерту жүргізілмейді.",
                    )}{" "}
                  </p>
                </div>
              </aside>
            </div>
          </>
        )}
        {step === "preflight" && (
          <>
            <div className="page-heading">
              <div>
                <span className="eyebrow">
                  {t("ДАЙЫНДЫҚ ·")} {session?.data.exam}
                </span>
                <h1>{t("Фотоға түсіп, емтиханды бастаңыз")}</h1>
                <p>
                  {t(
                    "Камераға тура қарап, бір фото түсіріңіз. Фото емтихан кезінде бетті салыстыру үшін қолданылады.",
                  )}{" "}
                </p>
              </div>
              <button className="btn secondary" onClick={finish}>
                {t("Дайындықты тоқтату")}{" "}
              </button>
            </div>
            <div className="preflight-grid">
              <section className="camera-card">
                <div className="camera-view">
                  {cameraStream || snapshot?.preview ? (
                    <img
                      src={cameraStream || snapshot.preview}
                      alt={t("Камераның локалды көрінісі")}
                    />
                  ) : (
                    <div className="camera-empty">
                      <Camera size={52} />
                      <p>
                        {cameraRequired
                          ? t("Камера кадрын күтеміз")
                          : t("Камерасыз бағдарламалық тест")}
                      </p>
                    </div>
                  )}
                </div>
                <div className="camera-caption">
                  <span className="live-dot" />
                  {t("Локалды камера")}{" "}
                  <span>
                    {snapshot?.status?.fps || 0}
                    {t("кадр/с · AI")} {snapshot?.status?.analysis_fps || 0}
                    {t("тексеру/с")}{" "}
                  </span>
                </div>
              </section>
              <section className="card checklist">
                <h2>{t("Дайындық нәтижесі")}</h2>
                {!cameraRequired && (
                  <div className="notice">
                    <AlertTriangle size={18} />
                    {t(
                      "Бағдарламалық тест профилі: камера және фото міндетті емес. Бұл физикалық прокторинг сынағы емес.",
                    )}{" "}
                  </div>
                )}
                <CheckRow
                  title={t("Камера дайын")}
                  ok={
                    !cameraRequired ||
                    (snapshot?.status?.models_ready &&
                      signals.faces === 1 &&
                      signals.quality === "good")
                  }
                  detail={
                    snapshot?.status?.camera_error ||
                    snapshot?.status?.model_error ||
                    (signals.faces === 1 && signals.quality === "good"
                      ? t("Бір бет анық көрінеді. Фотоға түсуге болады.")
                      : t("Камераға тура қарап, жарықты реттеңіз."))
                  }
                />
                {snapshot?.displays > 1 && (
                  <div className="notice error">
                    {t("Емтихан үшін бір монитор қажет.")}{" "}
                  </div>
                )}
                {session?.data.mode === "strict" && guard?.error && (
                  <ErrorBox error={guard.error} />
                )}
                {cameraRequired && (
                  <>
                    {snapshot?.identity?.photo && (
                      <div className="reference-photo">
                        <img
                          src={snapshot.identity.photo}
                          alt={t("Емтиханға тіркелген фото")}
                        />
                        <div>
                          <strong>{t("Бастапқы фото сақталды")}</strong>
                          <p>
                            {t(
                              "Емтихан кезіндегі бет осы фотомен салыстырылады.",
                            )}{" "}
                          </p>
                        </div>
                      </div>
                    )}
                    <button
                      className="btn primary wide"
                      disabled={
                        busy ||
                        !snapshot?.status?.models_ready ||
                        signals.faces !== 1 ||
                        signals.quality !== "good"
                      }
                      onClick={() =>
                        action(async () => {
                          await invoke("enroll");
                          setSnapshot(await invoke("snapshot"));
                        })
                      }
                    >
                      <Camera size={18} />
                      {snapshot?.status?.identity_enrolled
                        ? t("Фотоны қайта түсіру")
                        : t("Фотоға түсіру")}
                    </button>
                  </>
                )}
                <CheckRow
                  title={t("Микрофон")}
                  ok={
                    snapshot?.status?.microphone_running &&
                    !snapshot?.status?.microphone_error
                  }
                  detail={
                    session?.data.policy.microphone_required === false
                      ? t("Әкімшінің сынақ профилінде өшірілген")
                      : snapshot?.status?.microphone_error ||
                        t(
                          "Қосылған. Емтихан кезінде дыбыс оқиғалары тіркеледі.",
                        )
                  }
                />
                {session?.data.mode === "strict" ? (
                  <div className="auto-protection">
                    <ShieldCheck size={22} />
                    <div>
                      <strong>{t("Қорғаныс автоматты қосылады")}</strong>
                      <p>
                        {session.data.platform === "moodle"
                          ? "Moodle-дегі «Start attempt» басылғанда "
                          : "«Емтиханды бастау» басылғанда "}
                        {t(
                          "бөгде бағдарламалар жабылып, USB, қашықтан басқару және артық перне комбинацияларын шектейді. Емтихан аяқталғанда шектеулер қалпына келеді.",
                        )}{" "}
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="notice">
                    {t(
                      "Әкімшінің бағдарламалық сынақ профилі. Бұл сессия Windows шектеулерін өзгертпейді.",
                    )}{" "}
                  </div>
                )}
                <button
                  className="btn primary wide"
                  disabled={
                    busy ||
                    (cameraRequired && !snapshot?.status?.identity_enrolled) ||
                    (session?.data.policy.microphone_required &&
                      (!snapshot?.status?.microphone_running ||
                        !!snapshot?.status?.microphone_error))
                  }
                  onClick={() => action(start)}
                >
                  {busy
                    ? t("Емтихан беті ашылуда…")
                    : session.data.platform === "moodle"
                      ? t("Тест бетіне өту")
                      : t("Емтиханды бастау")}
                  <ChevronRight size={18} />
                </button>
                <button
                  className="btn text wide"
                  disabled={busy}
                  onClick={() =>
                    action(async () => {
                      setGuard((await invoke("probe")).guard);
                      setSnapshot(await invoke("snapshot"));
                    })
                  }
                >
                  <RefreshCw size={16} />
                  {t("Құрылғыларды қайта тексеру")}{" "}
                </button>
              </section>
            </div>
          </>
        )}
        {step === "exam" && exam && (
          <>
            <div className="exam-top">
              <div>
                <span className="eyebrow">{t("ЛОКАЛДЫ ЕМТИХАН")}</span>
                <h1>{session.data.exam}</h1>
              </div>
              <div className="timer">
                <Clock size={20} />
                {Math.floor(seconds / 60)}:
                {String(seconds % 60).padStart(2, "0")}
              </div>
            </div>
            <div className="exam-grid">
              <section className="card question">
                <span className="eyebrow">
                  {t("СҰРАҚ")} {question + 1} / {exam.questions.length}
                </span>
                <h2>{exam.questions[question].text}</h2>
                <div className="choices">
                  {exam.questions[question].choices.map(
                    (choice: string, index: number) => (
                      <button
                        key={choice}
                        className={
                          "choice " +
                          (exam.answers[exam.questions[question].id] === index
                            ? "selected"
                            : "")
                        }
                        onClick={() =>
                          action(async () => {
                            await invoke("answer", {
                              question_id: exam.questions[question].id,
                              answer: index,
                            });
                            setExam({
                              ...exam,
                              answers: {
                                ...exam.answers,
                                [exam.questions[question].id]: index,
                              },
                            });
                            setSaved(
                              new Date().toLocaleTimeString(getLocale()),
                            );
                          })
                        }
                      >
                        <span>{String.fromCharCode(65 + index)}</span>
                        {choice}
                      </button>
                    ),
                  )}
                </div>
                <div className="question-actions">
                  <button
                    className="btn secondary"
                    disabled={question === 0}
                    onClick={() => setQuestion(question - 1)}
                  >
                    <ArrowLeft size={16} />
                    {t("Алдыңғы")}{" "}
                  </button>
                  <span className="muted">
                    {saved ? "Сақталды: " + saved : t("Жауапты таңдаңыз")}
                  </span>
                  <button
                    className="btn primary"
                    disabled={question === exam.questions.length - 1}
                    onClick={() => setQuestion(question + 1)}
                  >
                    {t("Келесі")} <ChevronRight size={16} />
                  </button>
                </div>
              </section>
              <aside>
                <section className="card">
                  <h3>{t("Сұрақтар навигациясы")}</h3>
                  <div className="question-numbers">
                    {exam.questions.map((q: any, i: number) => (
                      <button
                        key={q.id}
                        className={
                          (i === question ? "current " : "") +
                          (exam.answers[q.id] !== undefined ? "answered" : "")
                        }
                        onClick={() => setQuestion(i)}
                      >
                        {i + 1}
                      </button>
                    ))}
                  </div>
                  <button className="btn primary wide" onClick={finish}>
                    {t("Тестті аяқтау")}{" "}
                  </button>
                </section>
                <section className="card mini-camera">
                  {(cameraStream || snapshot?.preview) && (
                    <img
                      src={cameraStream || snapshot.preview}
                      alt={t("Камера бақылауы")}
                    />
                  )}
                  <span className="live-dot" />
                  {cameraRequired
                    ? t("Бақылау қосулы")
                    : t("Камерасыз тест профилі")}
                  {session?.data.policy.microphone_required && (
                    <div className="microphone-live">
                      <Mic size={16} />
                      <span>
                        {t("Микрофон қосылған ·")}{" "}
                        {snapshot?.status?.microphone_dbfs ?? "—"} dBFS
                      </span>
                    </div>
                  )}
                  {signals.phone && (
                    <div className="notice error">
                      {t("Телефонды алып тастаңыз.")}
                    </div>
                  )}
                  {cameraRequired && signals.faces === 0 && (
                    <div className="notice">{t("Камераға оралыңыз.")}</div>
                  )}
                  {cameraRequired && signals.identity?.state === "mismatch" && (
                    <div className="notice error">
                      {t(
                        "Бет бастапқы фотомен сәйкеспейді. Мұғалім тексеретін оқиға тіркеледі.",
                      )}{" "}
                    </div>
                  )}
                </section>
              </aside>
            </div>
          </>
        )}
        {step === "finished" && (
          <section className="card finish-card">
            <span className="large-success">
              <ShieldCheck size={50} />
            </span>
            <h1>
              {result?.status === "interrupted"
                ? t("Сессия үзілді")
                : t("Сессия аяқталды")}
            </h1>
            <p>
              {t(
                "Оқиғалар журналы сақталды. Есеп мұғалім панелінде қолжетімді.",
              )}
            </p>
            {result?.status === "interrupted" && (
              <p role="status">
                {interruptionMessage(result?.data.interruption_reason)}
              </p>
            )}
            <Badge value={result?.status || "completed"} />
            <div className="finish-details">
              <span>{result?.data.student}</span>
              <strong>{result?.data.exam}</strong>
            </div>
            <button
              className="btn primary"
              onClick={() => {
                setSession(null);
                setSnapshot(null);
                setStep("welcome");
                setCameraStream("");
                setError("");
              }}
            >
              {t("Басты бетке оралу")}{" "}
            </button>
          </section>
        )}
      </main>
      <footer className="student-footer">
        {t("Sergек Proctor · Қырағы бақылау. Әділ бағалау.")}{" "}
        <span>{t("Бейне өңдеу — осы құрылғыда")}</span>
      </footer>
    </div>
  );
}

function CheckRow({
  title,
  ok,
  detail,
}: {
  title: string;
  ok: boolean;
  detail: string;
}) {
  return (
    <div className="check-row">
      {ok ? (
        <CheckCircle2 className="good" size={21} />
      ) : (
        <AlertTriangle className="warn" size={21} />
      )}
      <div>
        <strong>{title}</strong>
        <small>{friendlyError(detail)}</small>
      </div>
    </div>
  );
}

function Teacher({
  setup,
  onStudent,
  onSetup,
}: {
  setup: boolean;
  onStudent: () => void;
  onSetup: () => void;
}) {
  const [logged, setLogged] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("overview");
  const [sessions, setSessions] = useState<any[]>([]);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<any>(null);
  const [showTechnical, setShowTechnical] = useState(false);
  const visibleEvents =
    detail?.events?.filter(
      (item: any) => showTechnical || item.requires_review !== false,
    ) || [];
  const [profile, setProfile] = useState<any>(null);
  const [integration, setIntegration] = useState<any>(null);
  const [diagnostics, setDiagnostics] = useState<any>(null);
  const [query, setQuery] = useState("");
  const [evidence, setEvidence] = useState<any>(null);
  const [evidenceWaiting, setEvidenceWaiting] = useState(false);
  const [referencePhoto, setReferencePhoto] = useState<any>(null);
  const eventRequest = useRef(0);
  const [evidenceTrack, setEvidenceTrack] = useState("camera");
  const evidenceFrames =
    evidence?.tracks?.[evidenceTrack] || evidence?.frames || [];
  const [event, setEvent] = useState<any>(null);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [note, setNote] = useState("");
  const [newKey, setNewKey] = useState("");
  const [moodleKey, setMoodleKey] = useState("");
  const [hub, setHub] = useState({ enabled: false, url: "", pairing_key: "" });
  const action = async (fn: () => Promise<void>) => {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const reload = useCallback(async () => {
    const [list, p, i, d] = await Promise.all([
      api("/sessions"),
      api("/profile"),
      api("/integration"),
      api("/diagnostics"),
    ]);
    setSessions(list);
    setProfile((old: any) => old || p);
    setIntegration(i);
    setDiagnostics(d);
    if (selected) setDetail(await api("/sessions/" + selected));
  }, [selected]);
  useEffect(() => {
    api("/auth/me")
      .then(() => setLogged(true))
      .catch(() => {});
  }, []);
  useEffect(() => {
    if (!logged) return;
    reload().catch((e) => setError(e.message));
    const id = setInterval(() => reload().catch(() => {}), 3000);
    return () => clearInterval(id);
  }, [logged, reload]);
  useEffect(() => {
    if (!playing || !evidence) return;
    if (frame >= evidenceFrames.length - 1) {
      setPlaying(false);
      return;
    }
    const duration = Math.max(
      20,
      (evidenceFrames[frame + 1].time - evidenceFrames[frame].time) * 1000,
    );
    const id = setTimeout(() => setFrame((old) => old + 1), duration);
    return () => clearTimeout(id);
  }, [playing, evidence, frame]);
  useEffect(() => {
    if (!logged || !event || evidence || event.requires_review === false)
      return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const request = eventRequest.current;
    const deadline = Date.now() + 45000;
    setEvidenceWaiting(true);
    const poll = async () => {
      try {
        const clip = await api("/events/" + event.id + "/evidence");
        if (!alive || request !== eventRequest.current) return;
        setEvidence(clip);
        setEvidenceWaiting(false);
        if (!clip.tracks?.camera?.length && clip.tracks?.screen?.length)
          setEvidenceTrack("screen");
      } catch {
        if (!alive) return;
        if (Date.now() < deadline) timer = setTimeout(poll, 750);
        else setEvidenceWaiting(false);
      }
    };
    poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [logged, event?.id, !!evidence]);
  async function exitTeacher() {
    if (logged) {
      await api("/auth/logout", "POST");
      setLogged(false);
    }
    onStudent();
  }
  async function login() {
    if (setup) {
      await invoke("setup", { password });
      onSetup();
    }
    await api("/auth/login", "POST", { password });
    setPassword("");
    setLogged(true);
  }
  async function openEvent(item: any) {
    const request = ++eventRequest.current;
    setEvent(item);
    setEvidence(null);
    setReferencePhoto(null);
    setFrame(0);
    setEvidenceTrack("camera");
    setPlaying(false);
    setNote(item.note);
    const [reference, video] = await Promise.allSettled([
      api("/sessions/" + item.session_id + "/reference"),
      item.media
        ? api("/events/" + item.id + "/evidence")
        : Promise.resolve(null),
    ]);
    if (request !== eventRequest.current) return;
    if (reference.status === "fulfilled") setReferencePhoto(reference.value);
    if (video.status === "fulfilled" && video.value) {
      const clip = video.value;
      setEvidence(clip);
      if (!clip.tracks?.camera?.length && clip.tracks?.screen?.length)
        setEvidenceTrack("screen");
    }
  }
  if (!logged)
    return (
      <div className="login-page">
        <div className="login-top">
          <LanguageSelector />
          <Brand />
          <button className="btn text" onClick={() => action(exitTeacher)}>
            {t("Студент режимі")} <ChevronRight size={17} />
          </button>
        </div>
        <section className="card login-card">
          <span className="icon-tile">
            <Lock size={26} />
          </span>
          <span className="eyebrow">{t("МҰҒАЛІМ ПАНЕЛІ")}</span>
          <h1>{setup ? t("Алғашқы баптау") : t("Қош келдіңіз")}</h1>
          <p>
            {setup
              ? t("Әкімшілік құпиясөзді орнатыңыз. Кемінде 12 таңба.")
              : t("Сессиялар мен оқиғаларды тексеру үшін кіріңіз.")}
          </p>
          <ErrorBox error={error} />
          <form
            onSubmit={(e) => {
              e.preventDefault();
              action(login);
            }}
          >
            <label>
              {t("Құпиясөз")}{" "}
              <input
                autoComplete={setup ? "new-password" : "current-password"}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={setup ? 12 : 1}
              />
            </label>
            <button className="btn primary wide" disabled={busy || !password}>
              {setup ? t("Құпиясөзді орнату") : t("Панельге кіру")}
              <ChevronRight size={18} />
            </button>
          </form>
          {setup && !window.sergek && (
            <p className="warn">
              {t("Алғашқы баптау desktop қосымшасында жасалады.")}{" "}
            </p>
          )}
        </section>
        <div className="login-bottom">
          {t("Қолжетімділік тек уәкілетті оқытушыларға беріледі.")}{" "}
        </div>
      </div>
    );
  const active = sessions.filter((s) => s.status === "active").length;
  const allEvents = sessions.reduce((sum, s) => sum + s.event_count, 0);
  const filtered = sessions.filter((s) =>
    (s.data.student + " " + s.data.exam)
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  return (
    <div className="dashboard">
      <aside className="sidebar">
        <Brand />
        <div className="sidebar-university">
          <GraduationCap size={18} />
          <span>{profile?.university || t("Университет профилі")}</span>
        </div>
        <span className="nav-label">{t("БАҚЫЛАУ ОРТАЛЫҒЫ")}</span>
        <nav>
          {[
            ["overview", t("Шолу"), Activity],
            ["sessions", t("Сессиялар"), Monitor],
            ["settings", t("Емтихан ережелері"), Settings],
            ["integration", t("Интеграция"), Link2],
            ["diagnostics", t("Диагностика"), Server],
          ].map(([id, title, Icon]: any) => (
            <button
              key={id}
              className={tab === id ? "active" : ""}
              onClick={() => {
                setTab(id);
                setSelected("");
                setDetail(null);
              }}
            >
              <Icon size={19} />
              {title}
              {id === "sessions" && <span>{sessions.length}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div>
            <span className="live-dot" />
            {t("Локалды өңдеу")}{" "}
          </div>
          <p>{t("Оқиғалар — адам тексеруіне арналған.")}</p>
          <button
            onClick={() =>
              action(async () => {
                await api("/auth/logout", "POST");
                setLogged(false);
              })
            }
          >
            <LogOut size={17} />
            {t("Панельден шығу")}{" "}
          </button>
        </div>
      </aside>
      <div className="dashboard-body">
        <header className="dashboard-header">
          <LanguageSelector />
          <div>
            <span className="breadcrumb">{t("Бақылау орталығы")}</span>
            <ChevronRight size={14} />
            <strong>
              {
                (
                  {
                    overview: t("Шолу"),
                    sessions: t("Сессиялар"),
                    settings: t("Емтихан ережелері"),
                    integration: t("Интеграция"),
                    diagnostics: t("Диагностика"),
                  } as any
                )[tab]
              }
            </strong>
          </div>
          <button className="btn text" onClick={() => action(exitTeacher)}>
            {t("Студент режимі")} <Monitor size={17} />
          </button>
          <span className="avatar">{t("М")}</span>
        </header>
        <main className="dashboard-main">
          <ErrorBox error={error} />
          {["overview", "sessions"].includes(tab) && !selected && (
            <>
              <div className="page-heading">
                <div>
                  <span className="eyebrow">
                    {t("ЕМТИХАН ОРТАСЫНЫҢ БАҚЫЛАУЫ")}
                  </span>
                  <h1>
                    {tab === "overview"
                      ? t("Бәрі бір панельде.")
                      : t("Емтихан сессиялары")}
                  </h1>
                  <p>
                    {t(
                      "Сессия күйін, тіркелген оқиғаларды және тексеру нәтижелерін бақылаңыз.",
                    )}{" "}
                  </p>
                </div>
                <button
                  className="btn secondary"
                  onClick={() => action(reload)}
                >
                  <RefreshCw size={17} />
                  {t("Жаңарту")}{" "}
                </button>
              </div>
              <div className="stats-grid">
                <Stat
                  icon={Monitor}
                  title={t("Барлық сессия")}
                  value={sessions.length}
                  detail={t("Сақталған емтихан сессиялары")}
                />
                <Stat
                  icon={Activity}
                  title={t("Белсенді")}
                  value={active}
                  detail={t("Қазір бақылау жүргізілуде")}
                />
                <Stat
                  icon={Eye}
                  title={t("Тексерілетін оқиға")}
                  value={allEvents}
                  detail={t("Автоматты айыптау емес")}
                />
                <Stat
                  icon={ShieldCheck}
                  title={t("Аяқталған")}
                  value={
                    sessions.filter((s) => s.status === "completed").length
                  }
                  detail={t("Есебі қарауға дайын")}
                />
              </div>
              <section className="card sessions-card">
                <div className="table-heading">
                  <div>
                    <h2>{t("Сессиялар")}</h2>
                    <p>{t("Емтиханды таңдап, оқиғаларды тексеріңіз.")}</p>
                  </div>
                  <div className="search">
                    <Search size={17} />
                    <input
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder={t("Студент немесе емтихан")}
                    />
                  </div>
                </div>
                {filtered.length ? (
                  <table>
                    <thead>
                      <tr>
                        <th>{t("Студент / Емтихан")}</th>
                        <th>{t("Платформа")}</th>
                        <th>{t("Басталды")}</th>
                        <th>{t("Күй")}</th>
                        <th>{t("Оқиға")}</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map((item) => (
                        <tr
                          key={item.id}
                          onClick={() =>
                            action(async () => {
                              setSelected(item.id);
                              setDetail(await api("/sessions/" + item.id));
                            })
                          }
                        >
                          <td>
                            <strong>{item.data.student}</strong>
                            <span>{item.data.exam}</span>
                          </td>
                          <td>
                            <span className="platform-tag">
                              {item.data.platform}
                            </span>
                            {item.data.remote && (
                              <small>{t("Желілік агент")}</small>
                            )}
                          </td>
                          <td>
                            {item.started ? date(item.started) : t("Дайындық")}
                          </td>
                          <td>
                            <Badge value={item.status} />
                          </td>
                          <td>
                            <strong>{item.event_count}</strong>
                          </td>
                          <td>
                            <ChevronRight size={18} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="empty-state">
                    <Monitor size={42} />
                    <h3>{t("Сессия әлі жоқ")}</h3>
                    <p>
                      {t(
                        "Студент қосымшасынан алғашқы емтихан сессиясын бастаңыз.",
                      )}{" "}
                    </p>
                  </div>
                )}
              </section>
              {tab === "overview" && (
                <div className="overview-bottom">
                  <section className="card">
                    <span className="icon-tile">
                      <ShieldCheck />
                    </span>
                    <h3>{t("Мұғалім шешім қабылдайды")}</h3>
                    <p>
                      {t(
                        "Камера мен құрылғы оқиғалары дәлел контекстін береді. Әр оқиғаны растауға, негізсіз деп белгілеуге және пікір қосуға болады.",
                      )}{" "}
                    </p>
                  </section>
                  <section className="card">
                    <span className="icon-tile">
                      <Link2 />
                    </span>
                    <h3>{t("Платформаға бейімделеді")}</h3>
                    <p>
                      {t(
                        "Moodle плагині, Platonus қорғалған терезесі және университет профилі бір архитектурада.",
                      )}{" "}
                    </p>
                    <button
                      className="btn text"
                      onClick={() => setTab("integration")}
                    >
                      {t("Интеграцияны баптау")} <ChevronRight size={16} />
                    </button>
                  </section>
                </div>
              )}
            </>
          )}
          {selected && detail && (
            <>
              <button
                className="btn text back"
                onClick={() => {
                  setSelected("");
                  setDetail(null);
                }}
              >
                <ArrowLeft size={16} />
                {t("Сессияларға оралу")}{" "}
              </button>
              <div className="page-heading">
                <div>
                  <span className="eyebrow">{t("СЕССИЯ ЕСЕБІ")}</span>
                  <h1>{detail.session.data.student}</h1>
                  <p>
                    {detail.session.data.exam}
                    {t("· дайындалды:")} {date(detail.session.created)}
                    <br />
                    {t("Басталды:")}{" "}
                    {detail.session.started
                      ? date(detail.session.started)
                      : "—"}
                    {t("· Аяқталды:")}{" "}
                    {detail.session.ended ? date(detail.session.ended) : "—"}
                  </p>
                </div>
                <div className="button-row">
                  <Badge value={detail.session.status} />
                  <a
                    className="btn secondary"
                    href={`/api/sessions/${selected}/report/pdf?lang=${getLanguage()}`}
                    download={`sergek-${selected}.pdf`}
                  >
                    <Download size={16} />
                    PDF
                  </a>
                  <a
                    className="btn secondary"
                    href={`/api/sessions/${selected}/report/json`}
                    download={`sergek-${selected}.json`}
                  >
                    JSON
                  </a>
                  {["active", "preflight"].includes(detail.session.status) && (
                    <button
                      className="btn danger"
                      onClick={() =>
                        action(async () => {
                          await api("/sessions/" + selected + "/stop", "POST");
                          await reload();
                        })
                      }
                    >
                      {t("Сессияны тоқтату")}{" "}
                    </button>
                  )}
                </div>
              </div>
              <div className="notice">
                <ShieldCheck size={18} />
                {detail.integrity_ok
                  ? t("Оқиғалар журналының хэш тізбегі тексерілді.")
                  : t("Журнал тұтастығы бұзылған: тексеру қажет.")}
                <span className="muted">
                  {detail.session.data.mode === "strict"
                    ? t("Қорғалған емтихан")
                    : t("Әкімшінің бағдарламалық сынағы")}
                </span>
              </div>
              <section className="card">
                <h2>{t("Оқиғалар уақыт шкаласы")}</h2>
                <p>
                  {t(
                    "Бақылау оқиғалары мен қызмет ақауларын тексеріңіз. Техникалық жазбалар бөлек көрсетіледі.",
                  )}{" "}
                </p>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={showTechnical}
                    onChange={(e) => setShowTechnical(e.target.checked)}
                  />
                  {t("Техникалық журналды да көрсету")}{" "}
                </label>
                {visibleEvents.length ? (
                  <div className="timeline">
                    {visibleEvents.map((item: any) => (
                      <button
                        className="timeline-event"
                        key={item.id}
                        onClick={() => action(() => openEvent(item))}
                      >
                        <span className="timeline-icon">
                          <Eye size={18} />
                        </span>
                        <div>
                          <strong>{t(labels[item.kind] || item.kind)}</strong>
                          <p>
                            {date(item.created)}
                            {item.detail.duration_seconds
                              ? ` · ${item.detail.duration_seconds} ${t("секунд")}`
                              : ""}
                          </p>
                        </div>
                        {item.requires_review === false ? (
                          <span className="muted">{t("Техникалық жазба")}</span>
                        ) : (
                          <Badge value={item.verdict} />
                        )}
                        <span className="evidence-label">
                          {item.media ? t("Бейнеүзінді") : t("Метадерек")}
                        </span>
                        <ChevronRight size={17} />
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="empty-state">
                    <CheckCircle2 size={36} />
                    <h3>{t("Тексерілетін оқиға жоқ")}</h3>
                    <p>
                      {t(
                        "Бұл автоматты адалдық қорытындысы емес; есеп бақылау нәтижесін көрсетеді.",
                      )}{" "}
                    </p>
                  </div>
                )}
              </section>
              <section className="card technical">
                <h3>{t("Дайындық және қорғаныс нәтижесі")}</h3>
                <pre>
                  {JSON.stringify(
                    detail.session.data.preflight || {
                      status: t("Емтихан әлі басталмады"),
                    },
                    null,
                    2,
                  )}
                </pre>
              </section>
              {["completed", "interrupted"].includes(detail.session.status) && (
                <button
                  className="btn text danger"
                  onClick={() => {
                    if (
                      confirm(
                        t(
                          "Сессия мен бейнеүзінділерді қайтарымсыз жою керек пе?",
                        ),
                      )
                    )
                      action(async () => {
                        await api("/sessions/" + selected, "DELETE");
                        setSelected("");
                        await reload();
                      });
                  }}
                >
                  <Trash2 size={16} />
                  {t("Сессия деректерін жою")}{" "}
                </button>
              )}
            </>
          )}
          {tab === "settings" && profile && (
            <>
              <div className="page-heading">
                <div>
                  <span className="eyebrow">{t("ҰЙЫМ ПРОФИЛІ")}</span>
                  <h1>{t("Емтихан ережелері")}</h1>
                  <p>{t("Өзгерістер келесі сессияларға қолданылады.")}</p>
                </div>
                <button
                  className="btn primary"
                  disabled={busy}
                  onClick={() =>
                    action(async () => {
                      setProfile(await api("/profile", "PUT", profile));
                    })
                  }
                >
                  <Check size={17} />
                  {t("Сақтау")}{" "}
                </button>
              </div>
              <div className="settings-grid">
                <section className="card">
                  <h2>{t("Университет және платформалар")}</h2>
                  {[
                    ["university", t("Университет")],
                    ["moodle_url", t("Moodle мекенжайы")],
                    ["platonus_url", t("Platonus мекенжайы")],
                  ].map(([key, label]) => (
                    <label key={key}>
                      {label}
                      <input
                        value={profile[key]}
                        onChange={(e) =>
                          setProfile({ ...profile, [key]: e.target.value })
                        }
                      />
                    </label>
                  ))}
                  <label>
                    {t("Рұқсат етілген домендер")}{" "}
                    <textarea
                      value={profile.allowed_hosts.join("\n")}
                      onChange={(e) =>
                        setProfile({
                          ...profile,
                          allowed_hosts: e.target.value
                            .split("\n")
                            .map((s) => s.trim())
                            .filter(Boolean),
                        })
                      }
                    />
                    <small>
                      {t(
                        "Әр жолға бір домен. Авторизация мен ресурстардың қажетті домендерін де қосыңыз.",
                      )}{" "}
                    </small>
                  </label>
                  <label>
                    {t("Рұқсатсыз қолданбалар")}{" "}
                    <textarea
                      value={profile.policy.forbidden_processes.join("\n")}
                      onChange={(e) =>
                        setProfile({
                          ...profile,
                          policy: {
                            ...profile.policy,
                            forbidden_processes: e.target.value
                              .split("\n")
                              .filter(Boolean),
                          },
                        })
                      }
                    />
                  </label>
                </section>
                <section className="card">
                  <h2>{t("Бақылау саясаты")}</h2>
                  <label>
                    {t("Жеке TLS сертификаттары (host=SHA256)")}{" "}
                    <textarea
                      value={Object.entries(profile.tls_pins || {})
                        .map(([host, pin]) => host + " = " + pin)
                        .join("\n")}
                      onChange={(e) =>
                        setProfile({
                          ...profile,
                          tls_pins: Object.fromEntries(
                            e.target.value
                              .split("\n")
                              .filter((line) => line.includes("="))
                              .map((line) =>
                                line.split("=").map((v) => v.trim()),
                              ),
                          ),
                        })
                      }
                    />
                    <small>
                      {t(
                        "Әдеттегі сертификаттар автоматты тексеріледі. Локалды тест немесе университеттің жеке CA сертификаты үшін ғана нақты fingerprint енгізіңіз.",
                      )}{" "}
                    </small>
                  </label>
                  {[
                    [
                      "camera_required",
                      t("Камера және бастапқы фото міндетті"),
                    ],
                    [
                      "microphone_required",
                      t("Микрофон және дыбыс үзіндісі міндетті"),
                    ],
                    ["screen_recording", t("Экран үзінділерін тіркеу")],
                    [
                      "close_applications",
                      t("Емтихан басталғанда бөгде бағдарламаларды жабу"),
                    ],
                    ["remote_block", t("Қашықтан басқаруды бұғаттау")],
                    ["usb_block", t("Сыртқы жинақтауыштарды шектеу")],
                    ["keyboard_block", t("Перне қорғанысы")],
                    ["single_monitor", t("Бір монитор ғана")],
                    ["paper_allowed", t("Қағазға жазуға рұқсат")],
                    ["copy_paste", t("Көшіру / қоюға рұқсат")],
                  ].map(([key, label]) => (
                    <label className="toggle-row" key={key}>
                      <span>{label}</span>
                      <input
                        type="checkbox"
                        checked={profile.policy[key]}
                        onChange={(e) =>
                          setProfile({
                            ...profile,
                            policy: {
                              ...profile.policy,
                              [key]: e.target.checked,
                            },
                          })
                        }
                      />
                    </label>
                  ))}
                  {[
                    ["phone_seconds", t("Телефон тұрақтылығы, секунд")],
                    [
                      "phone_confidence",
                      t("Телефон анықтауының сенімділік шегі"),
                    ],
                    ["sound_seconds", t("Дауыс ұзақтығы, кемінде 3 секунд")],
                    ["gaze_seconds", t("Ұзақ қарау, секунд")],
                    ["absence_seconds", t("Бет жоғалуы, секунд")],
                    [
                      "identity_seconds",
                      t("Бет сәйкессіздігінің ұзақтығы, секунд"),
                    ],
                    ["identity_threshold", t("Бет ұқсастығының шегі")],
                    ["retention_days", t("Сақтау мерзімі, күн")],
                  ].map(([key, label]) => (
                    <label key={key}>
                      {label}
                      <input
                        type="number"
                        step={key === "identity_threshold" ? "0.001" : "0.1"}
                        min={key === "sound_seconds" ? 3 : undefined}
                        value={profile.policy[key]}
                        onChange={(e) =>
                          setProfile({
                            ...profile,
                            policy: {
                              ...profile.policy,
                              [key]: Number(e.target.value),
                            },
                          })
                        }
                      />
                    </label>
                  ))}
                </section>
              </div>
            </>
          )}
          {tab === "integration" && (
            <>
              <div className="page-heading">
                <div>
                  <span className="eyebrow">{t("БАЙЛАНЫС ҚАБАТЫ")}</span>
                  <h1>{t("Платформалар және аудитория")}</h1>
                  <p>{t("Тест платформасы мен мұғалім хабын қосыңыз.")}</p>
                </div>
              </div>
              <div className="settings-grid">
                <section className="card">
                  <span className="icon-tile">
                    <Link2 />
                  </span>
                  <h2>Moodle</h2>
                  <p>
                    {t(
                      "quizaccess_sergek плагині емтиханды локалды сессиямен байланыстырады. Университеттің нақты Moodle нұсқасында қабылдау тесті қажет.",
                    )}{" "}
                  </p>
                  <Badge
                    value={
                      integration?.moodle_configured
                        ? "configured"
                        : "not configured"
                    }
                  />
                  <button
                    className="btn secondary wide"
                    onClick={() =>
                      action(async () => {
                        setNewKey(
                          (
                            await api("/integration/rotate-key", "POST", {
                              kind: "moodle_key",
                            })
                          ).key,
                        );
                        await reload();
                      })
                    }
                  >
                    {t("Интеграция кілтін жасау / ауыстыру")}{" "}
                  </button>
                  <label>
                    {t("Ортақ Moodle кілтін импорттау")}{" "}
                    <input
                      type="password"
                      value={moodleKey}
                      onChange={(e) => setMoodleKey(e.target.value)}
                      autoComplete="off"
                    />
                  </label>
                  <button
                    className="btn secondary wide"
                    disabled={moodleKey.length < 32}
                    onClick={() =>
                      action(async () => {
                        await api("/integration/moodle", "PUT", {
                          key: moodleKey,
                        });
                        setMoodleKey("");
                        await reload();
                      })
                    }
                  >
                    {t("Moodle кілтін сақтау")}{" "}
                  </button>
                  <h3>Platonus</h3>
                  <p>
                    {t(
                      "Қорғалған браузер терезесі дайын. Нақты кіру, тест тапсыру және аяқтау аккаунтпен тексеріледі. Баға синхрондауы жария API расталғанға дейін қосылмайды.",
                    )}{" "}
                  </p>
                </section>
                <section className="card">
                  <span className="icon-tile">
                    <Server />
                  </span>
                  <h2>{t("Жергілікті мұғалім хабы")}</h2>
                  <p>
                    {t(
                      "Қабылдаушы хаб HTTPS арқылы іске қосылады. Агент оқиғалар мен шифрланған сақтауға арналған бейнеүзінділерді синхрондайды.",
                    )}{" "}
                  </p>
                  <button
                    className="btn secondary wide"
                    onClick={() =>
                      action(async () => {
                        setNewKey(
                          (
                            await api("/integration/rotate-key", "POST", {
                              kind: "hub_receive_key",
                            })
                          ).key,
                        );
                        await reload();
                      })
                    }
                  >
                    {t("Хабтың жұптау кілтін жасау")}{" "}
                  </button>
                  <label>
                    {t("Хаб HTTPS мекенжайы")}{" "}
                    <input
                      value={hub.url}
                      onChange={(e) => setHub({ ...hub, url: e.target.value })}
                      placeholder="https://proctor.university.kz:8765"
                    />
                  </label>
                  <label>
                    {t("Жұптау кілті")}{" "}
                    <input
                      type="password"
                      value={hub.pairing_key}
                      onChange={(e) =>
                        setHub({ ...hub, pairing_key: e.target.value })
                      }
                    />
                  </label>
                  <label className="toggle-row">
                    <span>{t("Осы агенттен синхрондау")}</span>
                    <input
                      type="checkbox"
                      checked={hub.enabled}
                      onChange={(e) =>
                        setHub({ ...hub, enabled: e.target.checked })
                      }
                    />
                  </label>
                  <button
                    className="btn primary wide"
                    onClick={() =>
                      action(async () => {
                        await api("/integration/hub", "PUT", hub);
                        await reload();
                      })
                    }
                  >
                    {t("Хаб байланысын сақтау")}{" "}
                  </button>
                  {integration?.status && (
                    <pre>{JSON.stringify(integration.status, null, 2)}</pre>
                  )}
                </section>
              </div>
              {newKey && (
                <section className="card secret-card">
                  <h3>{t("Жаңа кілт")}</h3>
                  <p>
                    {t(
                      "Оны тек плагин немесе уәкілетті агент баптауына енгізіңіз.",
                    )}{" "}
                  </p>
                  <code>{newKey}</code>
                  <button className="btn text" onClick={() => setNewKey("")}>
                    {t("Жасыру")}{" "}
                  </button>
                </section>
              )}
            </>
          )}
          {tab === "diagnostics" && (
            <>
              <div className="page-heading">
                <div>
                  <span className="eyebrow">{t("ЖҮЙЕ ДАЙЫНДЫҒЫ")}</span>
                  <h1>{t("Диагностика")}</h1>
                  <p>{t("Шынайы модель және қызмет күйі.")}</p>
                </div>
              </div>
              <section className="card">
                <CheckRow
                  title={t("AI модельдері")}
                  ok={diagnostics?.vision.models_ready}
                  detail={
                    diagnostics?.vision.model_error ||
                    t("Локалды модельдер жүктелген")
                  }
                />
                <CheckRow
                  title={t("Камера")}
                  ok={diagnostics?.vision.camera_running}
                  detail={
                    diagnostics?.vision.camera_error ||
                    t("Камера тек келісілген сессияда қосылады")
                  }
                />
                <pre>{JSON.stringify(diagnostics, null, 2)}</pre>
              </section>
            </>
          )}
        </main>
      </div>
      {event && (
        <div className="modal-backdrop">
          <section className="modal">
            <div className="modal-header">
              <div>
                <span className="eyebrow">{t("ОҚИҒАНЫ ТЕКСЕРУ")}</span>
                <h2>{t(labels[event.kind] || event.kind)}</h2>
                <p>{date(event.created)}</p>
              </div>
              <button
                className="btn text"
                onClick={() => {
                  setEvent(null);
                  setPlaying(false);
                }}
              >
                {t("Жабу")} <XCircle size={20} />
              </button>
            </div>
            {referencePhoto?.photo && (
              <div className="reference-photo">
                <img
                  src={referencePhoto.photo}
                  alt={t("Бастапқы тіркелген фото")}
                />
                <div>
                  <strong>{t("Бастапқы тіркелген фото")}</strong>
                  <p>
                    {t("Төмендегі камера үзіндісіндегі адаммен салыстырыңыз.")}
                  </p>
                </div>
              </div>
            )}
            {evidence?.tracks && (
              <div className="button-row">
                {Object.entries(evidence.tracks)
                  .filter(([, rows]: any) => rows.length)
                  .map(([track]) => (
                    <button
                      key={track}
                      className={
                        "btn " +
                        (evidenceTrack === track ? "primary" : "secondary")
                      }
                      onClick={() => {
                        setEvidenceTrack(track);
                        setFrame(0);
                        setPlaying(false);
                      }}
                    >
                      {track === "screen" ? t("Компьютер экраны") : t("Камера")}
                    </button>
                  ))}
              </div>
            )}
            {evidence?.audio?.src && (
              <div className="audio-evidence">
                <Mic size={20} />
                <div>
                  <strong>
                    {t("Оқиға кезіндегі дыбыс ·")}{" "}
                    {evidence.audio.duration.toFixed(1)} {t("с")}{" "}
                  </strong>
                  <p>
                    {t(
                      "Дыбыс белсенділігі автоматты айыптау болып саналмайды. Үзіндіні тыңдап, жағдайды бағалаңыз.",
                    )}{" "}
                  </p>
                  <audio controls preload="metadata" src={evidence.audio.src} />
                </div>
              </div>
            )}
            <div className="evidence-view">
              {evidenceFrames.length > 0 ? (
                <img
                  src={evidenceFrames[frame]?.image}
                  alt={t("Оқиғаның бейнеүзіндісі")}
                />
              ) : (
                <div className="camera-empty">
                  <FileText size={44} />
                  <p>
                    {evidenceWaiting
                      ? t("Оқиғаның бейне және дыбыс үзіндісі дайындалуда…")
                      : t("Осы оқиғада бейне үзіндісі жоқ.")}
                  </p>
                </div>
              )}
            </div>
            {evidenceFrames.length > 0 && (
              <div className="player-controls">
                <button
                  className="btn text"
                  onClick={() => {
                    if (frame === evidenceFrames.length - 1) setFrame(0);
                    setPlaying(!playing);
                  }}
                >
                  {playing ? <Pause size={18} /> : <Play size={18} />}
                </button>
                <input
                  type="range"
                  min="0"
                  max={evidenceFrames.length - 1}
                  value={frame}
                  onChange={(e) => {
                    setFrame(Number(e.target.value));
                    setPlaying(false);
                  }}
                />
                <span>
                  {evidenceFrames[frame]?.time.toFixed(1)}
                  {t("с")}
                </span>
              </div>
            )}
            <label>
              {t("Мұғалім пікірі")}{" "}
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={t("Контекст пен шешіміңізді жазыңыз")}
              />
            </label>
            {event.requires_review !== false && (
              <div className="button-row">
                <button
                  className="btn primary"
                  onClick={() =>
                    action(async () => {
                      await api("/events/" + event.id, "PATCH", {
                        verdict: "confirmed",
                        note,
                      });
                      setEvent(null);
                      await reload();
                    })
                  }
                >
                  <Check size={17} />
                  {t("Растау")}{" "}
                </button>
                <button
                  className="btn secondary"
                  onClick={() =>
                    action(async () => {
                      await api("/events/" + event.id, "PATCH", {
                        verdict: "dismissed",
                        note,
                      });
                      setEvent(null);
                      await reload();
                    })
                  }
                >
                  {t("Негізсіз деп белгілеу")}{" "}
                </button>
              </div>
            )}
            <details>
              <summary>{t("Оқиға метадеректері")}</summary>
              <pre>{JSON.stringify(event.detail, null, 2)}</pre>
            </details>
          </section>
        </div>
      )}
    </div>
  );
}
function Stat({
  icon: Icon,
  title,
  value,
  detail,
}: {
  icon: any;
  title: string;
  value: number;
  detail: string;
}) {
  return (
    <section className="card stat">
      <div>
        <span>{title}</span>
        <Icon size={20} />
      </div>
      <strong>{value}</strong>
      <p>{detail}</p>
    </section>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
