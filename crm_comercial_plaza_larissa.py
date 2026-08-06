import re
import shutil
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "prospectos_plaza_larissa.db"
UPLOADS_DIR = APP_DIR / "expedientes_clientes"
UPLOADS_DIR.mkdir(exist_ok=True)

ETAPAS = [
    "Contacto inicial", "Información enviada", "Visita programada",
    "Visita realizada", "Propuesta enviada", "Negociación",
    "Documentación", "Cerrado", "Descartado",
]
GIROS = [
    "Alimentos y bebidas", "Salud y farmacia", "Belleza y cuidado personal",
    "Servicios", "Comercio minorista", "Educación", "Fitness y bienestar",
    "Entretenimiento", "Financiero", "Otro",
]
ORIGENES = [
    "Recomendación", "Llamada", "WhatsApp", "Correo", "Redes sociales",
    "Visita a la plaza", "Corredor inmobiliario", "Otro",
]
PRIORIDADES = ["Alta", "Media", "Baja"]
RESPONSABLES = ["Yani", "Eleni", "Dimitri", "Taky", "Agente Inmobiliario"]
TIPOS_DOCUMENTO = [
    "INE", "Acta Constitutiva", "Comprobante de Domicilio", "CURP",
    "CSF", "Contrato", "Adicional",
]


def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_columns(cursor, table):
    return {row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}


def add_column_if_missing(cursor, table, column, definition):
    if column not in table_columns(cursor, table):
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prospectos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            negocio TEXT NOT NULL,
            contacto TEXT, telefono TEXT, correo TEXT, giro TEXT, origen TEXT,
            etapa TEXT NOT NULL, prioridad TEXT, locales_interes TEXT,
            superficie_requerida REAL DEFAULT 0,
            precio_m2 REAL DEFAULT 0,
            renta_ofrecida REAL DEFAULT 0,
            probabilidad INTEGER DEFAULT 10,
            fecha_contacto TEXT, proximo_seguimiento TEXT, responsable TEXT,
            agente_nombre TEXT, agente_agencia TEXT, agente_correo TEXT,
            agente_celular TEXT, agente_comision REAL DEFAULT 0,
            comentarios TEXT, fecha_creacion TEXT NOT NULL,
            fecha_actualizacion TEXT NOT NULL
        )
    """)
    add_column_if_missing(cur, "prospectos", "precio_m2", "REAL DEFAULT 0")
    add_column_if_missing(cur, "prospectos", "agente_nombre", "TEXT")
    add_column_if_missing(cur, "prospectos", "agente_agencia", "TEXT")
    add_column_if_missing(cur, "prospectos", "agente_correo", "TEXT")
    add_column_if_missing(cur, "prospectos", "agente_celular", "TEXT")
    add_column_if_missing(cur, "prospectos", "agente_comision", "REAL DEFAULT 0")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS seguimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prospecto_id INTEGER NOT NULL,
            fecha TEXT NOT NULL, tipo TEXT, detalle TEXT NOT NULL,
            siguiente_accion TEXT, siguiente_fecha TEXT,
            FOREIGN KEY(prospecto_id) REFERENCES prospectos(id) ON DELETE CASCADE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prospecto_id INTEGER UNIQUE,
            negocio TEXT NOT NULL,
            contacto TEXT, telefono TEXT, correo TEXT, giro TEXT, origen TEXT,
            prioridad TEXT, locales_interes TEXT,
            superficie_contratada REAL DEFAULT 0,
            precio_m2_cerrado REAL DEFAULT 0,
            renta_mensual_cerrada REAL DEFAULT 0,
            responsable TEXT, agente_nombre TEXT, agente_agencia TEXT,
            agente_correo TEXT, agente_celular TEXT, agente_comision REAL DEFAULT 0,
            comentarios TEXT,
            fecha_cierre TEXT NOT NULL,
            fecha_creacion TEXT NOT NULL,
            FOREIGN KEY(prospecto_id) REFERENCES prospectos(id) ON DELETE SET NULL
        )
    """)
    add_column_if_missing(cur, "clientes", "agente_nombre", "TEXT")
    add_column_if_missing(cur, "clientes", "agente_agencia", "TEXT")
    add_column_if_missing(cur, "clientes", "agente_correo", "TEXT")
    add_column_if_missing(cur, "clientes", "agente_celular", "TEXT")
    add_column_if_missing(cur, "clientes", "agente_comision", "REAL DEFAULT 0")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS documentos_cliente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            tipo_documento TEXT NOT NULL,
            nombre_original TEXT NOT NULL,
            ruta_archivo TEXT NOT NULL,
            fecha_carga TEXT NOT NULL,
            FOREIGN KEY(cliente_id) REFERENCES clientes(id) ON DELETE CASCADE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS locales (
            local TEXT PRIMARY KEY, planta TEXT, superficie_m2 REAL,
            estatus TEXT DEFAULT 'Disponible', prospecto_asignado INTEGER,
            FOREIGN KEY(prospecto_asignado) REFERENCES prospectos(id) ON DELETE SET NULL
        )
    """)
    # Garantiza un inventario completo de 32 unidades.
    # Locales 01–16: planta baja; locales 17–32: planta alta.
    existentes = {row[0] for row in cur.execute("SELECT local FROM locales").fetchall()}
    faltantes = []
    for i in range(1, 33):
        local = f"Local {i:02d}"
        planta = "Planta Baja" if i <= 16 else "Planta Alta"
        if local not in existentes:
            faltantes.append((local, planta, 0.0, "Disponible", None))
        else:
            cur.execute("UPDATE locales SET planta=? WHERE local=?", (planta, local))
    if faltantes:
        cur.executemany(
            "INSERT INTO locales(local, planta, superficie_m2, estatus, prospecto_asignado) VALUES(?,?,?,?,?)",
            faltantes,
        )
    conn.commit()
    conn.close()


def query_df(query, params=()):
    conn = get_connection()
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def execute(query, params=()):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def money(v):
    return f"${float(v or 0):,.0f}"


def parse_date(v):
    if not v:
        return None
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        return None


def load_prospectos():
    return query_df("SELECT * FROM prospectos ORDER BY fecha_actualizacion DESC")


def load_clientes():
    return query_df("SELECT * FROM clientes ORDER BY fecha_cierre DESC, id DESC")


def prospecto_label(row):
    return f"#{int(row['id'])} · {row['negocio']}"


def cliente_label(row):
    return f"#{int(row['id'])} · {row['negocio']}"


def safe_name(name):
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return clean or "archivo"


def guardar_documento(cliente_id, tipo, uploaded_file):
    folder = UPLOADS_DIR / f"cliente_{cliente_id}"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{stamp}_{safe_name(uploaded_file.name)}"
    path = folder / filename
    with open(path, "wb") as f:
        shutil.copyfileobj(uploaded_file, f)
    execute(
        """INSERT INTO documentos_cliente
           (cliente_id, tipo_documento, nombre_original, ruta_archivo, fecha_carga)
           VALUES (?, ?, ?, ?, ?)""",
        (cliente_id, tipo, uploaded_file.name, str(path), datetime.now().isoformat(timespec="seconds")),
    )


def convertir_a_cliente(prospecto_id, superficie, precio_m2, renta, fecha_cierre):
    p = query_df("SELECT * FROM prospectos WHERE id=?", (prospecto_id,))
    if p.empty:
        raise ValueError("No se encontró el prospecto.")
    r = p.iloc[0]
    existing = query_df("SELECT id FROM clientes WHERE prospecto_id=?", (prospecto_id,))
    if existing.empty:
        execute(
            """INSERT INTO clientes (
                prospecto_id, negocio, contacto, telefono, correo, giro, origen,
                prioridad, locales_interes, superficie_contratada, precio_m2_cerrado,
                renta_mensual_cerrada, responsable, agente_nombre, agente_agencia,
                agente_correo, agente_celular, agente_comision, comentarios,
                fecha_cierre, fecha_creacion
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (prospecto_id, r['negocio'], r['contacto'], r['telefono'], r['correo'], r['giro'],
             r['origen'], r['prioridad'], r['locales_interes'], superficie, precio_m2, renta,
             r['responsable'], r.get('agente_nombre', ''), r.get('agente_agencia', ''),
             r.get('agente_correo', ''), r.get('agente_celular', ''),
             float(r.get('agente_comision', 0) or 0), r['comentarios'],
             fecha_cierre.isoformat(), datetime.now().isoformat(timespec="seconds")),
        )
    else:
        execute(
            """UPDATE clientes SET superficie_contratada=?, precio_m2_cerrado=?,
               renta_mensual_cerrada=?, responsable=?, agente_nombre=?, agente_agencia=?,
               agente_correo=?, agente_celular=?, agente_comision=?, fecha_cierre=?
               WHERE prospecto_id=?""",
            (superficie, precio_m2, renta, r['responsable'], r.get('agente_nombre', ''),
             r.get('agente_agencia', ''), r.get('agente_correo', ''),
             r.get('agente_celular', ''), float(r.get('agente_comision', 0) or 0),
             fecha_cierre.isoformat(), prospecto_id),
        )
    execute(
        "UPDATE prospectos SET etapa='Cerrado', probabilidad=100, fecha_actualizacion=? WHERE id=?",
        (datetime.now().isoformat(timespec="seconds"), prospecto_id),
    )
    locales = [x.strip() for x in str(r['locales_interes'] or '').split(",") if x.strip()]
    for local in locales:
        execute(
            "UPDATE locales SET estatus='Contratado', prospecto_asignado=? WHERE local=?",
            (prospecto_id, local),
        )


st.set_page_config(page_title="CRM Comercial — Plaza Larissa", page_icon="🏬", layout="wide")
init_db()
st.title("🏬 CRM comercial — Plaza Larissa")
st.caption("Prospectos, cierres, clientes, expedientes y control comercial de las 32 unidades.")

pagina = st.sidebar.radio(
    "Sección", ["Resumen", "Prospectos", "Seguimientos", "Clientes", "Locales", "Exportar"]
)
prospectos = load_prospectos()
clientes = load_clientes()
hoy = date.today()

if pagina == "Resumen":
    activos = prospectos[~prospectos["etapa"].isin(["Cerrado", "Descartado"])] if not prospectos.empty else prospectos
    negociacion = prospectos[prospectos["etapa"].isin(["Propuesta enviada", "Negociación", "Documentación"])] if not prospectos.empty else prospectos
    renta_cerrada = clientes["renta_mensual_cerrada"].fillna(0).sum() if not clientes.empty else 0
    vencidos = proximos_7 = 0
    if not prospectos.empty:
        fechas = pd.to_datetime(prospectos["proximo_seguimiento"], errors="coerce").dt.date
        abiertos = ~prospectos["etapa"].isin(["Cerrado", "Descartado"])
        vencidos = int(((fechas < hoy) & abiertos).sum())
        proximos_7 = int(((fechas >= hoy) & (fechas <= hoy + timedelta(days=7)) & abiertos).sum())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Prospectos activos", len(activos))
    c2.metric("En negociación", len(negociacion))
    c3.metric("Clientes cerrados", len(clientes))
    c4.metric("Renta mensual cerrada", money(renta_cerrada))
    c5.metric("Seguimientos vencidos", vencidos)
    st.caption(f"Próximos seguimientos en 7 días: {proximos_7}")

    inventario = query_df("SELECT local, planta, estatus FROM locales ORDER BY local")
    pb = inventario[inventario["planta"] == "Planta Baja"]
    pa = inventario[inventario["planta"] == "Planta Alta"]
    pb_ocupados = int((pb["estatus"] == "Contratado").sum())
    pa_ocupados = int((pa["estatus"] == "Contratado").sum())
    pb_pct = pb_ocupados / len(pb) if len(pb) else 0
    pa_pct = pa_ocupados / len(pa) if len(pa) else 0

    st.subheader("Ocupación por planta")
    oc1, oc2 = st.columns(2)
    with oc1:
        st.write(f"**Planta baja:** {pb_ocupados} de {len(pb)} unidades ({pb_pct:.0%})")
        st.progress(pb_pct)
    with oc2:
        st.write(f"**Planta alta:** {pa_ocupados} de {len(pa)} unidades ({pa_pct:.0%})")
        st.progress(pa_pct)

    if prospectos.empty:
        st.info("Todavía no hay prospectos. Ve a **Prospectos** para registrar el primero.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Embudo comercial")
            embudo = prospectos.groupby("etapa").size().reindex(ETAPAS, fill_value=0).reset_index(name="Prospectos")
            st.bar_chart(embudo.set_index("etapa"))
        with col2:
            st.subheader("Valor comercial")
            abiertos = prospectos[~prospectos["etapa"].isin(["Descartado", "Cerrado"])]
            potencial = abiertos["renta_ofrecida"].fillna(0).sum()
            ponderado = (abiertos["renta_ofrecida"].fillna(0) * abiertos["probabilidad"].fillna(0) / 100).sum()
            st.metric("Renta potencial abierta", money(potencial))
            st.metric("Renta ponderada abierta", money(ponderado))
            st.metric("Renta mensual ya cerrada", money(renta_cerrada))

elif pagina == "Prospectos":
    inventario_locales = query_df("SELECT local FROM locales ORDER BY local")
    opciones_locales = inventario_locales["local"].tolist()

    tab1, tab2 = st.tabs(["Listado, edición y cierre", "Nuevo prospecto"])

    with tab2:
        st.subheader("Registrar prospecto")
        c1, c2, c3 = st.columns(3)
        negocio = c1.text_input("Negocio o marca *", key="nuevo_negocio")
        contacto = c2.text_input("Persona de contacto", key="nuevo_contacto")
        telefono = c3.text_input("Teléfono", key="nuevo_telefono")

        c1, c2, c3 = st.columns(3)
        correo = c1.text_input("Correo", key="nuevo_correo")
        giro_base = c2.selectbox("Giro", GIROS, key="nuevo_giro_base")
        origen = c3.selectbox("Origen", ORIGENES, key="nuevo_origen")
        giro_otro = ""
        if giro_base == "Otro":
            giro_otro = st.text_input("Especifica el giro", key="nuevo_giro_otro")
        giro = giro_otro.strip() if giro_base == "Otro" else giro_base

        c1, c2, c3 = st.columns(3)
        etapa = c1.selectbox("Etapa", ETAPAS[:-2], index=0, key="nuevo_etapa")
        prioridad = c2.selectbox("Prioridad", PRIORIDADES, index=1, key="nuevo_prioridad")
        responsable = c3.selectbox("Responsable", RESPONSABLES, index=0, key="nuevo_responsable")
        agente_nombre = agente_agencia = agente_correo = agente_celular = ""
        agente_comision = 0.0
        if responsable == "Agente Inmobiliario":
            st.markdown("**Datos del agente inmobiliario**")
            a1, a2, a3 = st.columns(3)
            agente_nombre = a1.text_input("Nombre del agente", key="nuevo_agente_nombre")
            agente_agencia = a2.text_input("Agencia", key="nuevo_agente_agencia")
            agente_correo = a3.text_input("Correo del agente", key="nuevo_agente_correo")
            a1, a2 = st.columns(2)
            agente_celular = a1.text_input("Celular del agente", key="nuevo_agente_celular")
            agente_comision = a2.number_input("Comisión ofrecida (%)", min_value=0.0, max_value=100.0, step=0.5, key="nuevo_agente_comision")

        locales_seleccionados = st.multiselect(
            "Locales de interés",
            opciones_locales,
            placeholder="Selecciona uno o varios locales",
            key="nuevo_locales",
        )

        c1, c2, c3 = st.columns(3)
        superficie = c1.number_input("Superficie requerida (m²)", min_value=0.0, step=5.0, key="nuevo_superficie")
        precio_m2 = c2.number_input("Precio por m²", min_value=0.0, step=10.0, key="nuevo_precio_m2")
        renta_calculada = superficie * precio_m2
        c3.metric("Renta mensual ofrecida", money(renta_calculada))

        c1, c2, c3 = st.columns(3)
        probabilidad = c1.slider("Probabilidad de cierre (%)", 0, 100, 10, 5, key="nuevo_probabilidad")
        fecha_contacto = c2.date_input("Fecha de contacto", value=hoy, key="nuevo_fecha_contacto")
        proximo = c3.date_input("Próximo seguimiento", value=hoy + timedelta(days=7), key="nuevo_proximo")
        comentarios = st.text_area("Comentarios", key="nuevo_comentarios")

        if st.button("Guardar prospecto", type="primary", key="guardar_nuevo_prospecto"):
            if not negocio.strip():
                st.error("El nombre del negocio es obligatorio.")
            elif giro_base == "Otro" and not giro_otro.strip():
                st.error("Especifica el nombre del giro.")
            else:
                ahora = datetime.now().isoformat(timespec="seconds")
                execute("""INSERT INTO prospectos (
                    negocio, contacto, telefono, correo, giro, origen, etapa, prioridad,
                    locales_interes, superficie_requerida, precio_m2, renta_ofrecida,
                    probabilidad, fecha_contacto, proximo_seguimiento, responsable,
                    agente_nombre, agente_agencia, agente_correo, agente_celular,
                    agente_comision, comentarios, fecha_creacion, fecha_actualizacion
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (negocio.strip(), contacto.strip(), telefono.strip(), correo.strip(), giro, origen,
                 etapa, prioridad, ", ".join(locales_seleccionados), superficie, precio_m2, renta_calculada,
                 probabilidad, fecha_contacto.isoformat(), proximo.isoformat(), responsable,
                 agente_nombre.strip(), agente_agencia.strip(), agente_correo.strip(),
                 agente_celular.strip(), agente_comision, comentarios.strip(), ahora, ahora))
                st.success("Prospecto guardado.")
                st.rerun()

    with tab1:
        if prospectos.empty:
            st.info("No hay prospectos registrados.")
        else:
            st.dataframe(prospectos[["id", "negocio", "contacto", "giro", "etapa", "locales_interes",
                                      "superficie_requerida", "precio_m2", "renta_ofrecida",
                                      "probabilidad", "proximo_seguimiento"]],
                         use_container_width=True, hide_index=True)
            opciones = {prospecto_label(r): int(r["id"]) for _, r in prospectos.iterrows()}
            seleccion = st.selectbox("Selecciona un prospecto", list(opciones.keys()))
            pid = opciones[seleccion]
            r = prospectos[prospectos["id"] == pid].iloc[0]

            with st.expander("Editar ficha", expanded=True):
                c1, c2, c3 = st.columns(3)
                negocio = c1.text_input("Negocio o marca", value=r["negocio"] or "", key=f"edit_negocio_{pid}")
                contacto = c2.text_input("Contacto", value=r["contacto"] or "", key=f"edit_contacto_{pid}")
                telefono = c3.text_input("Teléfono", value=r["telefono"] or "", key=f"edit_telefono_{pid}")

                giro_actual = r["giro"] or ""
                giro_base_actual = giro_actual if giro_actual in GIROS else "Otro"
                c1, c2, c3 = st.columns(3)
                correo = c1.text_input("Correo", value=r["correo"] or "", key=f"edit_correo_{pid}")
                giro_base = c2.selectbox("Giro", GIROS, index=GIROS.index(giro_base_actual), key=f"edit_giro_base_{pid}")
                origen = c3.selectbox("Origen", ORIGENES, index=ORIGENES.index(r["origen"]) if r["origen"] in ORIGENES else 0, key=f"edit_origen_{pid}")
                giro_otro = ""
                if giro_base == "Otro":
                    giro_otro = st.text_input(
                        "Especifica el giro",
                        value=giro_actual if giro_actual not in GIROS else "",
                        key=f"edit_giro_otro_{pid}",
                    )
                giro = giro_otro.strip() if giro_base == "Otro" else giro_base

                c1, c2, c3 = st.columns(3)
                etapa = c1.selectbox("Etapa", ETAPAS, index=ETAPAS.index(r["etapa"]) if r["etapa"] in ETAPAS else 0, key=f"edit_etapa_{pid}")
                prioridad = c2.selectbox("Prioridad", PRIORIDADES, index=PRIORIDADES.index(r["prioridad"]) if r["prioridad"] in PRIORIDADES else 1, key=f"edit_prioridad_{pid}")
                responsable_actual = r["responsable"] if r["responsable"] in RESPONSABLES else "Yani"
                responsable = c3.selectbox(
                    "Responsable", RESPONSABLES,
                    index=RESPONSABLES.index(responsable_actual),
                    key=f"edit_responsable_{pid}",
                )
                agente_nombre = agente_agencia = agente_correo = agente_celular = ""
                agente_comision = 0.0
                if responsable == "Agente Inmobiliario":
                    st.markdown("**Datos del agente inmobiliario**")
                    a1, a2, a3 = st.columns(3)
                    agente_nombre = a1.text_input("Nombre del agente", value=r.get("agente_nombre", "") or "", key=f"edit_agente_nombre_{pid}")
                    agente_agencia = a2.text_input("Agencia", value=r.get("agente_agencia", "") or "", key=f"edit_agente_agencia_{pid}")
                    agente_correo = a3.text_input("Correo del agente", value=r.get("agente_correo", "") or "", key=f"edit_agente_correo_{pid}")
                    a1, a2 = st.columns(2)
                    agente_celular = a1.text_input("Celular del agente", value=r.get("agente_celular", "") or "", key=f"edit_agente_celular_{pid}")
                    agente_comision = a2.number_input(
                        "Comisión ofrecida (%)", min_value=0.0, max_value=100.0,
                        value=float(r.get("agente_comision", 0) or 0), step=0.5,
                        key=f"edit_agente_comision_{pid}",
                    )

                actuales = [x.strip() for x in str(r["locales_interes"] or "").split(",") if x.strip() in opciones_locales]
                locales = st.multiselect(
                    "Locales de interés",
                    opciones_locales,
                    default=actuales,
                    key=f"edit_locales_{pid}",
                )

                c1, c2, c3 = st.columns(3)
                superficie = c1.number_input("Superficie requerida (m²)", min_value=0.0, value=float(r["superficie_requerida"] or 0), step=5.0, key=f"edit_superficie_{pid}")
                precio_m2 = c2.number_input("Precio por m²", min_value=0.0, value=float(r["precio_m2"] or 0), step=10.0, key=f"edit_precio_{pid}")
                renta = superficie * precio_m2
                c3.metric("Renta mensual ofrecida", money(renta))

                c1, c2 = st.columns(2)
                probabilidad = c1.slider("Probabilidad de cierre (%)", 0, 100, int(r["probabilidad"] or 0), 5, key=f"edit_probabilidad_{pid}")
                proximo = c2.date_input("Próximo seguimiento", value=parse_date(r["proximo_seguimiento"]) or hoy, key=f"edit_proximo_{pid}")
                comentarios = st.text_area("Comentarios", value=r["comentarios"] or "", key=f"edit_comentarios_{pid}")

                if st.button("Guardar cambios", type="primary", key=f"guardar_edit_{pid}"):
                    if giro_base == "Otro" and not giro_otro.strip():
                        st.error("Especifica el nombre del giro.")
                    else:
                        execute("""UPDATE prospectos SET negocio=?, contacto=?, telefono=?, correo=?, giro=?, origen=?, etapa=?,
                            prioridad=?, locales_interes=?, superficie_requerida=?, precio_m2=?, renta_ofrecida=?, probabilidad=?,
                            proximo_seguimiento=?, responsable=?, agente_nombre=?, agente_agencia=?,
                            agente_correo=?, agente_celular=?, agente_comision=?,
                            comentarios=?, fecha_actualizacion=? WHERE id=?""",
                            (negocio.strip(), contacto.strip(), telefono.strip(), correo.strip(), giro, origen, etapa, prioridad,
                             ", ".join(locales), superficie, precio_m2, renta, probabilidad, proximo.isoformat(), responsable,
                             agente_nombre.strip(), agente_agencia.strip(), agente_correo.strip(),
                             agente_celular.strip(), agente_comision, comentarios.strip(),
                             datetime.now().isoformat(timespec="seconds"), pid))
                        st.success("Cambios guardados.")
                        st.rerun()

            st.divider()
            st.subheader("Cerrar renta y convertir en cliente")
            if r["etapa"] == "Cerrado":
                st.success("Este prospecto ya está convertido en cliente.")
            else:
                c1, c2, c3, c4 = st.columns(4)
                sup_cierre = c1.number_input(
                    "Superficie contratada (m²)",
                    min_value=0.0,
                    value=float(r["superficie_requerida"] or 0),
                    step=5.0,
                    key=f"cierre_sup_{pid}",
                )
                pm2_cierre = c2.number_input(
                    "Precio cerrado por m²",
                    min_value=0.0,
                    value=float(r["precio_m2"] or 0),
                    step=10.0,
                    key=f"cierre_pm2_{pid}",
                )
                renta_cierre = sup_cierre * pm2_cierre
                c3.metric("Renta mensual cerrada", money(renta_cierre))
                fecha_cierre = c4.date_input("Fecha de cierre", value=hoy, key=f"cierre_fecha_{pid}")
                confirmar = st.checkbox("Confirmo que la negociación quedó cerrada", key=f"cierre_confirmar_{pid}")
                if st.button("Convertir en cliente", type="primary", key=f"convertir_{pid}"):
                    if not confirmar:
                        st.error("Marca la confirmación antes de convertirlo.")
                    elif renta_cierre <= 0:
                        st.error("La renta mensual cerrada debe ser mayor a cero.")
                    else:
                        convertir_a_cliente(pid, sup_cierre, pm2_cierre, renta_cierre, fecha_cierre)
                        st.success("Renta cerrada. El registro ya aparece en Clientes.")
                        st.rerun()

elif pagina == "Seguimientos":
    abiertos = prospectos[~prospectos["etapa"].isin(["Cerrado", "Descartado"])] if not prospectos.empty else prospectos
    if abiertos.empty:
        st.info("No hay prospectos abiertos para seguimiento.")
    else:
        opciones = {prospecto_label(r): int(r["id"]) for _, r in abiertos.iterrows()}
        sel = st.selectbox("Prospecto", list(opciones.keys()))
        pid = opciones[sel]
        with st.form("nuevo_seguimiento", clear_on_submit=True):
            c1, c2 = st.columns(2)
            fecha_seg = c1.date_input("Fecha", value=hoy)
            tipo = c2.selectbox("Tipo", ["Llamada", "WhatsApp", "Correo", "Reunión", "Visita", "Propuesta", "Otro"])
            detalle = st.text_area("Detalle del seguimiento *")
            siguiente_accion = st.text_input("Siguiente acción")
            siguiente_fecha = st.date_input("Fecha de la siguiente acción", value=hoy + timedelta(days=7))
            if st.form_submit_button("Registrar seguimiento", type="primary"):
                if not detalle.strip():
                    st.error("Escribe el detalle del seguimiento.")
                else:
                    execute("INSERT INTO seguimientos(prospecto_id, fecha, tipo, detalle, siguiente_accion, siguiente_fecha) VALUES(?,?,?,?,?,?)",
                            (pid, fecha_seg.isoformat(), tipo, detalle.strip(), siguiente_accion.strip(), siguiente_fecha.isoformat()))
                    execute("UPDATE prospectos SET proximo_seguimiento=?, fecha_actualizacion=? WHERE id=?",
                            (siguiente_fecha.isoformat(), datetime.now().isoformat(timespec="seconds"), pid))
                    st.success("Seguimiento registrado.")
                    st.rerun()
        historial = query_df("SELECT fecha, tipo, detalle, siguiente_accion, siguiente_fecha FROM seguimientos WHERE prospecto_id=? ORDER BY fecha DESC, id DESC", (pid,))
        st.dataframe(historial, use_container_width=True, hide_index=True)

elif pagina == "Clientes":
    st.subheader("Clientes y expedientes")
    if clientes.empty:
        st.info("Todavía no hay clientes. Convierte un prospecto cuando se cierre la renta.")
    else:
        st.metric("Renta mensual cerrada total", money(clientes["renta_mensual_cerrada"].fillna(0).sum()))
        st.dataframe(clientes[["id", "negocio", "contacto", "telefono", "correo", "giro", "locales_interes",
                                    "superficie_contratada", "precio_m2_cerrado", "renta_mensual_cerrada", "fecha_cierre"]],
                     use_container_width=True, hide_index=True)
        opciones = {cliente_label(r): int(r["id"]) for _, r in clientes.iterrows()}
        sel = st.selectbox("Selecciona un cliente", list(opciones.keys()))
        cid = opciones[sel]
        cliente = clientes[clientes["id"] == cid].iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.write(f"**Contacto:** {cliente['contacto'] or '—'}")
        c1.write(f"**Teléfono:** {cliente['telefono'] or '—'}")
        c2.write(f"**Correo:** {cliente['correo'] or '—'}")
        c2.write(f"**Giro:** {cliente['giro'] or '—'}")
        c3.write(f"**Local(es):** {cliente['locales_interes'] or '—'}")
        c3.write(f"**Renta mensual:** {money(cliente['renta_mensual_cerrada'])}")
        if cliente["responsable"] == "Agente Inmobiliario":
            st.info(
                f"Agente: {cliente.get('agente_nombre', '') or '—'} · "
                f"Agencia: {cliente.get('agente_agencia', '') or '—'} · "
                f"Correo: {cliente.get('agente_correo', '') or '—'} · "
                f"Celular: {cliente.get('agente_celular', '') or '—'} · "
                f"Comisión: {float(cliente.get('agente_comision', 0) or 0):.1f}%"
            )

        st.subheader("Expediente documental")
        docs = query_df("SELECT id, tipo_documento, nombre_original, ruta_archivo, fecha_carga FROM documentos_cliente WHERE cliente_id=? ORDER BY fecha_carga DESC", (cid,))
        resumen = []
        for tipo in TIPOS_DOCUMENTO[:-1]:
            cantidad = int((docs["tipo_documento"] == tipo).sum()) if not docs.empty else 0
            resumen.append({"Documento": tipo, "Estatus": "Cargado" if cantidad else "Pendiente", "Archivos": cantidad})
        st.dataframe(pd.DataFrame(resumen), use_container_width=True, hide_index=True)

        with st.form("cargar_documentos", clear_on_submit=True):
            st.caption("Puedes seleccionar varios archivos en cada campo.")
            cargas = {}
            for tipo in TIPOS_DOCUMENTO[:-1]:
                cargas[tipo] = st.file_uploader(tipo, accept_multiple_files=True, key=f"up_{cid}_{tipo}")
            cargas["Adicional"] = st.file_uploader("Adicionales", accept_multiple_files=True, key=f"up_{cid}_adicional")
            if st.form_submit_button("Guardar documentos", type="primary"):
                total = 0
                for tipo, archivos in cargas.items():
                    for archivo in archivos or []:
                        guardar_documento(cid, tipo, archivo)
                        total += 1
                if total:
                    st.success(f"Se guardaron {total} archivo(s).")
                    st.rerun()
                else:
                    st.warning("Selecciona al menos un archivo.")

        if not docs.empty:
            st.subheader("Archivos almacenados")
            for _, d in docs.iterrows():
                path = Path(d["ruta_archivo"])
                cols = st.columns([2, 4, 2, 1])
                cols[0].write(d["tipo_documento"])
                cols[1].write(d["nombre_original"])
                cols[2].write(d["fecha_carga"])
                if path.exists():
                    with open(path, "rb") as f:
                        cols[3].download_button("Descargar", data=f.read(), file_name=d["nombre_original"], key=f"dl_{d['id']}")
                else:
                    cols[3].caption("No disponible")

        st.warning("En Streamlit Cloud estos archivos todavía pueden perderse al reiniciarse la app. Al conectar Supabase usaremos Supabase Storage para conservarlos permanentemente.")

elif pagina == "Locales":
    st.subheader("Inventario de 32 unidades")
    st.caption("Locales 01–16: planta baja. Locales 17–32: planta alta.")
    locales = query_df("""SELECT l.local, l.planta, l.superficie_m2, l.estatus, l.prospecto_asignado, p.negocio
                          FROM locales l LEFT JOIN prospectos p ON p.id=l.prospecto_asignado ORDER BY l.local""")
    editados = st.data_editor(locales[["local", "planta", "superficie_m2", "estatus"]], use_container_width=True, hide_index=True,
        disabled=["local", "planta"], column_config={
            "estatus": st.column_config.SelectboxColumn("Estatus", options=["Disponible", "Apartado", "En negociación", "Contratado"]),
            "superficie_m2": st.column_config.NumberColumn("Superficie (m²)", min_value=0.0, step=1.0),
        })
    if st.button("Guardar inventario"):
        for _, row in editados.iterrows():
            numero = int(str(row["local"]).split()[-1])
            planta = "Planta Baja" if numero <= 16 else "Planta Alta"
            execute("UPDATE locales SET planta=?, superficie_m2=?, estatus=? WHERE local=?",
                    (planta, row["superficie_m2"], row["estatus"], row["local"]))
        st.success("Inventario actualizado.")
        st.rerun()

elif pagina == "Exportar":
    seguimientos = query_df("""SELECT s.*, p.negocio FROM seguimientos s LEFT JOIN prospectos p ON p.id=s.prospecto_id ORDER BY s.fecha DESC""")
    locales = query_df("""SELECT l.*, p.negocio FROM locales l LEFT JOIN prospectos p ON p.id=l.prospecto_asignado ORDER BY l.local""")
    documentos = query_df("""SELECT d.*, c.negocio FROM documentos_cliente d LEFT JOIN clientes c ON c.id=d.cliente_id ORDER BY d.fecha_carga DESC""")
    for label, df, filename in [
        ("Descargar prospectos CSV", prospectos, "prospectos_plaza_larissa.csv"),
        ("Descargar clientes CSV", clientes, "clientes_plaza_larissa.csv"),
        ("Descargar seguimientos CSV", seguimientos, "seguimientos_plaza_larissa.csv"),
        ("Descargar locales CSV", locales, "locales_plaza_larissa.csv"),
        ("Descargar índice documental CSV", documentos, "documentos_clientes_plaza_larissa.csv"),
    ]:
        st.download_button(label, data=df.to_csv(index=False).encode("utf-8-sig"), file_name=filename, mime="text/csv")
    st.warning("La versión actual usa SQLite y almacenamiento local. La siguiente etapa será migrar datos y documentos a Supabase.")
