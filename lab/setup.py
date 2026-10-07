"""Isolated Moodle 4.5.15 lab: no Windows services, global PATH or trust-store changes."""

from pathlib import Path
import os, sys, json, secrets, subprocess, time, shutil, urllib.request, zipfile, hashlib
from datetime import datetime, timezone, timedelta
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import ipaddress

ROOT = Path(__file__).resolve().parent.parent
workspace_lab = ROOT.parent.parent / "work" / "local-moodle"
default_lab = (
    workspace_lab
    if ROOT.parent.name == "outputs" and workspace_lab.exists()
    else ROOT / "work" / "local-moodle"
)
LAB = Path(os.environ.get("SERGEK_LAB", default_lab)).resolve()
PACKAGES = {
    "moodle": (
        "https://codeload.github.com/moodle/moodle/zip/refs/tags/v4.5.15",
        "7ed9aaa3c256414a32a6d2832319131415896f27e260f614129de52881d00cf5",
    ),
    "php": (
        "https://downloads.php.net/~windows/releases/archives/php-8.3.35-nts-Win32-vs16-x64.zip",
        "25a8e2ac9ff30f1d768d1447c09a600617fa6e6082729f6e95f008b59c91fe45",
    ),
    "mariadb": (
        "https://dlm.mariadb.com/4425161/MariaDB/mariadb-11.4.8/winx64-packages/mariadb-11.4.8-winx64.zip",
        "ed86e93157af46317bb49161451c2ec258498a6fa8e68ca821ef1d780d855e6b",
    ),
}
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def run(args, **kwargs):
    return subprocess.run(
        [str(a) for a in args], creationflags=FLAGS, check=True, **kwargs
    )


def certificate():
    if (LAB / "localhost.crt").exists():
        return
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Sergek isolated localhost lab")]
    )
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=90))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    (LAB / "localhost.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (LAB / "localhost.key").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def prepare():
    LAB.mkdir(parents=True, exist_ok=True)
    for name, (url, digest) in PACKAGES.items():
        target = LAB / (name + ".zip")
        if not target.exists():
            print("Downloading", name, flush=True)
            if name == "mariadb":
                url += "?local_lab=" + str(int(time.time()))
            with urllib.request.urlopen(
                url, timeout=90
            ) as response, target.with_suffix(".part").open("wb") as out:
                shutil.copyfileobj(response, out)
            target.with_suffix(".part").rename(target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise RuntimeError(
                name + " archive checksum mismatch; preserve it for inspection"
            )
        folder = LAB / name
        if not (folder / "extracted.ok").exists():
            print("Extracting", name, flush=True)
            folder.mkdir(exist_ok=True)
            with zipfile.ZipFile(target) as archive:
                archive.extractall(folder)
            (folder / "extracted.ok").write_text("ok")
    certificate()
    credentials = LAB / "credentials.json"
    if not credentials.exists():
        credentials.write_text(
            json.dumps(
                {
                    "dbroot": secrets.token_hex(24),
                    "dbpass": secrets.token_hex(24),
                    "admin": "labteacher",
                    "adminpass": "L!" + secrets.token_urlsafe(24),
                    "student": "labstudent",
                    "studentpass": "S!" + secrets.token_urlsafe(24),
                    "sharedkey": secrets.token_urlsafe(40),
                    "hubkey": secrets.token_urlsafe(40),
                    "teacherpass": "T!" + secrets.token_urlsafe(24),
                },
                indent=2,
            )
        )
    values = json.loads(credentials.read_text())
    php = LAB / "php" / "php.exe"
    dbbin = LAB / "mariadb" / "mariadb-11.4.8-winx64" / "bin"
    moodle = LAB / "moodle" / "moodle-4.5.15"
    ext = (LAB / "php" / "ext").as_posix()
    ca = (LAB / "localhost.crt").as_posix()
    (LAB / "php" / "php.ini").write_text(
        f'extension_dir="{ext}"\n'
        + "".join(
            "extension=" + e + "\n"
            for e in [
                "curl",
                "intl",
                "mbstring",
                "mysqli",
                "openssl",
                "zip",
                "gd",
                "fileinfo",
                "sodium",
            ]
        )
        + f'date.timezone=Asia/Oral\nmemory_limit=512M\nmax_input_vars=5000\npost_max_size=64M\nupload_max_filesize=64M\ncurl.cainfo="{ca}"\nopenssl.cafile="{ca}"\ndisplay_errors=Off\nlog_errors=On\n'
    )
    datadir = LAB / "db"
    if not (datadir / "mysql").exists():
        run(
            [
                dbbin / "mariadb-install-db.exe",
                "--datadir=" + str(datadir),
                "--password=" + values["dbroot"],
                "--port=3308",
            ]
        )
    import psutil

    pids = (
        json.loads((LAB / "pids.json").read_text())
        if (LAB / "pids.json").exists()
        else {}
    )
    running = False
    if pids.get("db") and psutil.pid_exists(pids["db"]):
        try:
            running = (
                Path(psutil.Process(pids["db"]).exe()).resolve()
                == (dbbin / "mariadbd.exe").resolve()
            )
        except psutil.Error:
            pass
    if not running:
        log = (LAB / "db.log").open("ab")
        process = subprocess.Popen(
            [
                str(dbbin / "mariadbd.exe"),
                "--defaults-file=" + str(datadir / "my.ini"),
                "--port=3308",
                "--bind-address=127.0.0.1",
            ],
            stdout=log,
            stderr=log,
            creationflags=FLAGS,
        )
        pids["db"] = process.pid
        (LAB / "pids.json").write_text(json.dumps(pids))
        time.sleep(3)
        if process.poll() is not None:
            raise RuntimeError("MariaDB failed; inspect db.log")
    env = {**os.environ, "MYSQL_PWD": values["dbroot"]}
    sql = f"CREATE DATABASE IF NOT EXISTS sergek_moodle CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; CREATE USER IF NOT EXISTS 'sergek'@'127.0.0.1' IDENTIFIED BY '{values['dbpass']}'; GRANT ALL ON sergek_moodle.* TO 'sergek'@'127.0.0.1';"
    run(
        [dbbin / "mariadb.exe", "--host=127.0.0.1", "--port=3308", "--user=root"],
        input=sql.encode(),
        env=env,
    )
    destination = moodle / "mod" / "quiz" / "accessrule" / "sergek"
    shutil.copytree(
        ROOT / "moodle" / "quizaccess_sergek", destination, dirs_exist_ok=True
    )
    if not (moodle / "config.php").exists():
        print("Installing Moodle schema and Sergek access rule", flush=True)
        run(
            [
                php,
                moodle / "admin" / "cli" / "install.php",
                "--non-interactive",
                "--agree-license",
                "--dbtype=mariadb",
                "--dbhost=127.0.0.1",
                "--dbport=3308",
                "--dbname=sergek_moodle",
                "--dbuser=sergek",
                "--dbpass=" + values["dbpass"],
                "--wwwroot=https://localhost",
                "--dataroot=" + str(LAB / "moodledata"),
                "--fullname=Sergek local acceptance lab",
                "--shortname=Sergek Lab",
                "--adminuser=" + values["admin"],
                "--adminpass=" + values["adminpass"],
                "--adminemail=teacher@localhost.invalid",
            ]
        )
    config = moodle / "config.php"
    content = config.read_text()
    marker = "require_once(__DIR__ . '/lib/setup.php');"
    additions = (
        "\n$CFG->sslproxy = true;\n$CFG->slasharguments = false;\n$CFG->curlsecurityblockedhosts = '';\n$CFG->curlsecurityallowedport = '9443';\n$CFG->curlcafile = '"
        + ca
        + "';\n"
    )
    if "$CFG->sslproxy" not in content:
        config.write_text(content.replace(marker, additions + marker))
    run([php, moodle / "admin" / "cli" / "upgrade.php", "--non-interactive"])
    (LAB / "lab.json").write_text(
        json.dumps(
            {
                "root": str(ROOT),
                "lab": str(LAB),
                "php": str(php),
                "moodle": str(moodle),
                "url": "https://localhost/",
                "hub": "https://localhost:9443",
                "fingerprint": x509.load_pem_x509_certificate(
                    (LAB / "localhost.crt").read_bytes()
                )
                .fingerprint(hashes.SHA256())
                .hex(),
            },
            indent=2,
        )
    )
    print("Lab installed. Private credentials:", credentials, flush=True)


if __name__ == "__main__":
    prepare()
