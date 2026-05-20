import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

# ==========================================
# 1. CONFIGURACIÓN DE LA PÁGINA 
# ==========================================
st.set_page_config(
    page_title="PBO - Empresas Polar", 
    page_icon="🏢", 
    layout="centered"
)

# Inicializar un disparador en el estado de la sesión para controlar la actualización de caché
if "refresh_db" not in st.session_state:
    st.session_state["refresh_db"] = False

# --- LOGO OFICIAL ---
logo_url = "https://empresaspolar.com"
try:
    st.image(logo_url, width=280)
except Exception as e:
    pass

st.title("📋 Producto Bajo Observación (PBO)")
st.caption("Sistema interno de control y monitoreo de producto retenido — Empresas Polar")

# ==========================================
# 2. CONEXIÓN Y GESTIÓN DE BASE DE DATOS TRIPLE-OPTIMIZADA
# ==========================================
def get_db_connection():
    return psycopg2.connect(
        host=st.secrets["DB_HOST"],
        database=st.secrets["DB_NAME"],
        user=st.secrets["DB_USER"],
        password=st.secrets["DB_PASSWORD"],
        port=st.secrets["DB_PORT"]
    )

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lotes_db (
            id_pbo TEXT PRIMARY KEY, producto TEXT, formato TEXT, lote TEXT, orden TEXT,
            fecha_produccion TEXT, defecto_general TEXT, cantidad_total_latas INTEGER, ubicacion TEXT
        );
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS paletas_db (
            id SERIAL PRIMARY KEY, id_pbo TEXT REFERENCES lotes_db (id_pbo) ON DELETE CASCADE,
            nro_ticket TEXT UNIQUE, camadas_sueltas INTEGER, defecto TEXT, nca REAL, estatus TEXT
        );
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reproceso_db (
            id SERIAL PRIMARY KEY, id_pbo TEXT REFERENCES lotes_db (id_pbo) ON DELETE CASCADE,
            tickets_originales_consumidos TEXT, nuevo_ticket_reprocesado TEXT UNIQUE,
            camadas_sueltas INTEGER, estatus_calidad TEXT, estatus_logistica TEXT, observacion_laboratorio TEXT
        );
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historico_pbo_db (
            id_pbo TEXT PRIMARY KEY, producto TEXT, lote TEXT, fecha_cierre TEXT, motivo_cierre TEXT, operador_cierre TEXT
        );
    ''')
    cursor.execute('CREATE TABLE IF NOT EXISTS historico_paletas_db (id SERIAL PRIMARY KEY, id_pbo TEXT, nro_ticket TEXT, camadas_sueltas INTEGER, defecto TEXT, nca REAL, estatus TEXT);')
    cursor.execute('CREATE TABLE IF NOT EXISTS historico_reproceso_db (id SERIAL PRIMARY KEY, id_pbo TEXT, tickets_originales_consumidos TEXT, nuevo_ticket_reprocesado TEXT, camadas_sueltas INTEGER, estatus_calidad TEXT, estatus_logistica TEXT, observacion_laboratorio TEXT);')
    conn.commit()
    cursor.close()
    conn.close()

try:
    init_db()
except Exception as e:
    st.error(f"Error de red: {e}")

# --- 🚀 CONTROL DE CACHÉ DE ALTA VELOCIDAD ---
@st.cache_data(ttl=60, show_spinner="Cargando datos de planta desde Brasil...")
def cargar_datos_infraestructura(trigger_refresh):
    """Carga todas las tablas principales en un solo viaje de red y las almacena en RAM"""
    conn = get_db_connection()
    lotes = pd.read_sql_query("SELECT * FROM lotes_db", conn)
    paletas = pd.read_sql_query("SELECT * FROM paletas_db", conn)
    reprocesos = pd.read_sql_query("SELECT * FROM reproceso_db", conn)
    historico = pd.read_sql_query("SELECT * FROM historico_pbo_db", conn)
    conn.close()
    return lotes, paletas, reprocesos, historico

# Carga relámpago asistida por caché
lotes_activos_df, paletas_activas_df, reprocesos_activos_df, historico_pbo_df = cargar_datos_infraestructura(st.session_state["refresh_db"])

def forzar_actualizacion_red():
    """Limpia la memoria caché cuando ocurre una transacción de escritura"""
    st.cache_data.clear()
    st.session_state["refresh_db"] = not st.session_state["refresh_db"]

# Listas globales fijas
ESTATUS_OPCIONES = ["Sin reprocesar", "Reprocesado", "Briqueteado", "Aceptado con desviación"]
ESTATUS_DICTAMEN_CALIDAD = ["En Control de Calidad", "Chequeado", "Liberado"]
ESTATUS_DICTAMEN_LOGISTICA = ["En espera", "Confirmado", "Inconsistencia"]
UBICACIONES_LOGISTICA = ["Almacen de PBO", "Transicion", "Almacen de PT"]

# ==========================================
# 3. AUTOMATIZACIÓN DE CIERRE INDUSTRIAL 
# ==========================================
def ejecutar_higiene_y_cierre_automatico(usuario_actual):
    if lotes_activos_df.empty:
        return
        
    conn = get_db_connection()
    for _, lote in lotes_activos_df.iterrows():
        pbo_id = lote["id_pbo"]
        
        # Filtrar localmente en memoria en lugar de ir a la base de datos por cada lote
        df_orig = paletas_activas_df[paletas_activas_df["id_pbo"] == pbo_id]
        df_rep = reprocesos_activos_df[reprocesos_activos_df["id_pbo"] == pbo_id]
        
        condicion_originales = not df_orig.empty and not (df_orig["estatus"] == "Sin reprocesar").any()
        condicion_nuevas = not df_rep.empty and (df_rep["estatus_calidad"] == "Liberado").all() and (df_rep["estatus_logistica"] == "Confirmado").all()
        
        if condicion_originales and condicion_nuevas:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO historico_pbo_db VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING;",
                    (pbo_id, lote["producto"], lote["lote"], datetime.now().strftime("%Y-%m-%d %H:%M"), "Cierre Automático Integral", usuario_actual)
                )
                for _, row in df_orig.iterrows():
                    cursor.execute("INSERT INTO historico_paletas_db (id_pbo, nro_ticket, camadas_sueltas, defecto, nca, estatus) VALUES (%s, %s, %s, %s, %s, %s);", (pbo_id, row["nro_ticket"], row["camadas_sueltas"], row["defecto"], row["nca"], row["estatus"]))
                for _, row in df_rep.iterrows():
                    cursor.execute("INSERT INTO historico_reproceso_db (id_pbo, tickets_originales_consumidos, nuevo_ticket_reprocesado, camadas_sueltas, estatus_calidad, estatus_logistica, observacion_laboratorio) VALUES (%s, %s, %s, %s, %s, %s, %s);", (pbo_id, row["tickets_originales_consumidos"], row["nuevo_ticket_reprocesado"], row["camadas_sueltas"], row["estatus_calidad"], row["estatus_logistica"], row["observacion_laboratorio"]))
                
                cursor.execute("DELETE FROM lotes_db WHERE id_pbo = %s;", (pbo_id,))
                cursor.execute("DELETE FROM paletas_db WHERE id_pbo = %s;", (pbo_id,))
                cursor.execute("DELETE FROM reproceso_db WHERE id_pbo = %s;", (pbo_id,))
                
                conn.commit()
                forzar_actualizacion_red()
                st.rerun()
            except Exception as e:
                conn.rollback()
            finally:
                cursor.close()
    conn.close()

# ==========================================
# 4. BARRA LATERAL (CONTROL DE ACCESO)
# ==========================================
st.sidebar.header("🔑 Identificación de Usuario")
usuario = st.sidebar.text_input("Nombre del Operador", value="Operador de Turno")
departamento = st.sidebar.selectbox("Selecciona tu Departamento", ["Público / Solo Lectura", "🔬 Calidad", "🛠️ Reproceso / Operaciones", "📦 Logística"])

try:
    ejecutar_higiene_y_cierre_automatico(usuario)
except:
    pass

# ==========================================
# 5. PANEL DE CONTROL GENERAL (KPIs INDUSTRIALES)
# ==========================================
st.subheader("📊 Panel de Control PBO Activo")

total_pbos = len(lotes_activos_df)
total_latas_retenidas = lotes_activos_df["cantidad_total_latas"].sum() if not lotes_activos_df.empty else 0
paletas_pendientes = len(paletas_activas_df[paletas_activas_df["estatus"] == "Sin reprocesar"]) if not paletas_activas_df.empty else 0

kpi1, kpi2, kpi3 = st.columns(3)
kpi1.metric("PBOs Activos en Planta", total_pbos)
kpi2.metric("Total Latas Retenidas", f"{total_latas_retenidas:,}")
kpi3.metric("Paletas Sin Reprocesar", paletas_pendientes)

st.divider()
st.write("### 🚨 Lotes bajo Observación en Línea")
st.dataframe(lotes_activos_df, use_container_width=True, hide_index=True)

# ==========================================
# 6. PANEL DINÁMICO POR DEPARTAMENTO
# ==========================================
st.divider()
st.subheader("⚡ Acciones Disponibles")

if departamento == "Público / Solo Lectura":
    st.info("Visualización general activa. No tienes permisos para modificar datos.")

elif "Calidad" in departamento:
    st.error("🔒 Permisos de Nivel: CALIDAD")
    accion_calidad = st.radio("¿Qué acción deseas ejecutar?", ["➕ Crear Nuevo PBO", "📦 Añadir Paletas", "🔄 Actualización de Paletas", "🔬 Dictamen de Reproceso", "🗑️ Eliminar PBO"], horizontal=True)
    st.divider()

    if lotes_activos_df.empty and accion_calidad != "➕ Crear Nuevo PBO":
        st.warning("No hay casos PBO activos en planta en este momento.")
    else:
        if accion_calidad == "➕ Crear Nuevo PBO":
            with st.form("form_crear_pbo", clear_on_submit=True):
                st.write("### Crear Encabezado Macro de PBO")
                prod = st.text_input("Producto (Ej: Malta Polar)")
                formato = st.selectbox("Formato de Envase", ["8.4 oz", "12oz Sleek", "355ml Regular"])
                lote_prod = st.text_input("Lote de Producción")
                orden_prod = st.text_input("Orden de Fabricación (SAP)")
                fecha_p = st.date_input("Fecha de Producción", datetime.now())
                defecto_gen = st.text_input("Defecto General Detectado")
                cant_pbo = st.number_input("Cantidad Total de Latas Involucradas", min_value=1, value=1000)
                
                if st.form_submit_button("Generar PBO en Base de Datos"):
                    if prod and lote_prod and orden_prod and defecto_gen:
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("SELECT COUNT(*) FROM historico_pbo_db;")
                        total_historicos = cursor.fetchone()[0]
                        total_activos = len(lotes_activos_df)
                        nuevo_id_pbo = f"PBO-{total_historicos + total_activos + 1:03d} ({prod})"
                        
                        try:
                            cursor.execute("INSERT INTO lotes_db VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Almacen de PBO');", (nuevo_id_pbo, prod, formato, lote_prod, orden_prod, str(fecha_p), defecto_gen, cant_pbo))
                            conn.commit()
                            forzar_actualizacion_red()
                            st.success(f"¡{nuevo_id_pbo} registrado!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                        finally:
                            cursor.close()
                            conn.close()

        elif accion_calidad == "📦 Añadir Paletas":
            pbo_seleccionado = st.selectbox("Selecciona el PBO específico", lotes_activos_df["id_pbo"])
            defecto_heredado = lotes_activos_df[lotes_activos_df["id_pbo"] == pbo_seleccionado]["defecto_general"].values[0]
            num_paletas_a_crear = st.number_input("¿Cuántas paletas/tickets?", min_value=1, max_value=20, value=3)
            
            df_plantilla = pd.DataFrame({"Nro Ticket": [""] * num_paletas_a_crear, "Camadas Sueltas": [0] * num_paletas_a_crear, "Defecto Específico": [defecto_heredado] * num_paletas_a_crear, "% NCA": [0.0] * num_paletas_a_crear, "Estatus": ["Sin reprocesar"] * num_paletas_a_crear})
            tabla_ingreso = st.data_editor(df_plantilla, hide_index=True, use_container_width=True)
            
            if st.button("💾 Guardar Bloque de Paletas"):
                if "" in tabla_ingreso["Nro Ticket"].values: 
                    st.error("Error: Llene los números de ticket.")
                else:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    errores = False
                    for _, fila in tabla_ingreso.iterrows():
                        try:
                            cursor.execute("INSERT INTO paletas_db (id_pbo, nro_ticket, camadas_sueltas, defecto, nca, estatus) VALUES (%s, %s, %s, %s, %s, %s);", (pbo_seleccionado, fila["Nro Ticket"], int(fila["Camadas Sueltas"]), fila["Defecto Específico"], float(fila["% NCA"]), fila["Estatus"]))
                        except:
                            st.error("Error: El ticket ya existe en la red.")
                            errores = True
                            break
                    if not errores:
                        conn.commit()
                        forzar_actualizacion_red()
                        st.success("¡Paletas guardadas!")
                        st.rerun()
                    cursor.close()
                    conn.close()

        elif accion_calidad == "🔄 Actualización de Paletas":
            pbo_ver = st.selectbox("Filtra por PBO:", lotes_activos_df["id_pbo"])
            df_paletas_pbo = paletas_activas_df[paletas_activas_df["id_pbo"] == pbo_ver] if not paletas_activas_df.empty else pd.DataFrame()
            
            if df_paletas_pbo.empty: 
                st.warning("No hay paletas asignadas.")
            else:
                tickets_seleccionados = st.multiselect("Tickets a actualizar:", options=df_paletas_pbo["nro_ticket"].unique())
                if tickets_seleccionados:
                    with st.form("form_guardado_unico_directo"):
                        mod_estatus = st.selectbox("Cambiar Estatus Operacional a:", ["-- No modificar estatus --"] + ESTATUS_OPCIONES)
                        escribir_nuevo_defecto = st.checkbox("Modificar defecto")
                        mod_defecto = st.text_input("Nuevo Defecto:", disabled=not escribir_nuevo_defecto)
                        mod_nca = st.number_input("Modificar % NCA (-1 para ignorar):", min_value=-1.0, value=-1.0)
                        mod_camadas = st.number_input("Actualizar Nro Camadas (-1 para ignorar):", min_value=-1, value=-1)
                        
                        if st.form_submit_button("💾 Aplicar Cambios"):
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            for tkt in tickets_seleccionados:
                                if mod_estatus != "-- No modificar estatus --":
                                    cursor.execute("UPDATE paletas_db SET estatus = %s WHERE nro_ticket = %s;", (mod_estatus, tkt))
                                if escribir_nuevo_defecto and mod_defecto:
                                    cursor.execute("UPDATE paletas_db SET defecto = %s WHERE nro_ticket = %s;", (mod_defecto, tkt))
                                if mod_nca != -1.0:
                                    cursor.execute("UPDATE paletas_db SET nca = %s WHERE nro_ticket = %s;", (mod_nca, tkt))
                                if mod_camadas != -1:
                                    cursor.execute("UPDATE paletas_db SET camadas_sueltas = %s WHERE nro_ticket = %s;", (mod_camadas, tkt))
                            conn.commit()
                            cursor.close()
                            conn.close()
                            forzar_actualizacion_red()
                            st.success("¡Base de datos en la nube actualizada!")
                            st.rerun()

        elif accion_calidad == "🔬 Dictamen de Reproceso":
            pbo_evaluar = st.selectbox("Selecciona el PBO a dictaminar:", lotes_activos_df["id_pbo"])
            df_reproceso_pbo = reprocesos_activos_df[reprocesos_activos_df["id_pbo"] == pbo_evaluar] if not reprocesos_activos_df.empty else pd.DataFrame()
            
            if df_reproceso_pbo.empty: 
                st.warning("No cuenta con registros de paletas nuevas de reproceso.")
            else:
                tickets_evaluar = st.multiselect("Tickets de reproceso a dictaminar:", options=df_reproceso_pbo["nuevo_ticket_reprocesado"].unique())
                if tickets_evaluar:
                    with st.form("form_dictamen_masivo_lab"):
                        nuevo_estatus_rep = st.selectbox("Estatus Dictamen Control de Calidad:", ESTATUS_DICTAMEN_CALIDAD)
                        observacion_lab = st.text_area("Observación Técnica:")
                        
                        if st.form_submit_button("💾 Estampar Firma"):
                            if observacion_lab:
                                conn = get_db_connection()
                                cursor = conn.cursor()
                                for tkt in tickets_evaluar:
                                    cursor.execute("UPDATE reproceso_db SET estatus_calidad = %s, observacion_laboratorio = %s WHERE nuevo_ticket_reprocesado = %s;", (nuevo_estatus_rep, f"[{usuario}]: {observacion_lab}", tkt))
                                conn.commit()
                                cursor.close()
                                conn.close()
                                forzar_actualizacion_red()
                                st.success("¡Dictamen grabado!")
                                st.rerun()

        elif accion_calidad == "🗑️ Eliminar PBO":
            pbo_a_borrar = st.selectbox("Selecciona el caso PBO a remover:", lotes_activos_df["id_pbo"])
            motivo_cancelacion = st.text_input("Escribe el motivo detallado (Obligatorio):")
            
            if st.button("❌ Confirmar Eliminación", type="primary"):
                if motivo_cancelacion:
                    conn = get_db_connection()
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    cursor.execute("SELECT * FROM lotes_db WHERE id_pbo = %s;", (pbo_a_borrar,))
                    lote_data = cursor.fetchone()
                    df_orig_del = paletas_activas_df[paletas_activas_df["id_pbo"] == pbo_a_borrar]
                    df_rep_del = reprocesos_activos_df[reprocesos_activos_df["id_pbo"] == pbo_a_borrar]
                    
                    try:
                        cursor.execute("INSERT INTO historico_pbo_db VALUES (%s, %s, %s, %s, %s, %s);", (pbo_a_borrar, lote_data["producto"], lote_data["lote"], datetime.now().strftime("%Y-%m-%d %H:%M"), f"Cancelado manual por Calidad. Motivo: {motivo_cancelacion}", usuario))
                        cursor.execute("DELETE FROM lotes_db WHERE id_pbo = %s;", (pbo_a_borrar,))
                        conn.commit()
                        forzar_actualizacion_red()
                        st.success("¡Caso removido de planta!")
                        st.rerun()
                    except Exception as e:
                        conn.rollback()
                    finally:
                        cursor.close()
                        conn.close()

elif "Reproceso" in departamento:
    st.warning("🛠️ Permisos de Nivel: REPROCESO")
    if lotes_activos_df.empty: 
        st.info("No hay casos PBO abiertos.")
    else:
        pbo_target = st.selectbox("Selecciona el caso PBO asignado a tu línea", lotes_activos_df["id_pbo"])
        df_originales_pbo = paletas_activas_df[paletas_activas_df["id_pbo"] == pbo_target] if not paletas_activas_df.empty else pd.DataFrame()
        
        if df_originales_pbo.empty: 
            st.warning("Este caso no posee paletas cargadas.")
        else:
            tickets_consumidos = st.multiselect("Tickets ORIGINALES consumidos:", options=df_originales_pbo["nro_ticket"].unique())
        
            if tickets_consumidos:
                num_nuevos_tickets = st.number_input("¿Cuántas paletas NUEVAS se generaron?", min_value=1, value=2)
                df_plantilla_rep = pd.DataFrame({"Nuevo Ticket Reprocesado": [""] * num_nuevos_tickets, "Camadas Sueltas": [0] * num_nuevos_tickets})
                tabla_reproceso = st.data_editor(df_plantilla_rep, hide_index=True, use_container_width=True)
                
                if st.button("🚀 Registrar Cierre de Línea"):
                    if "" in tabla_reproceso["Nuevo Ticket Reprocesado"].values: 
                        st.error("Rellene los tickets generados.")
                    else:
                        cadena_consumidos = ", ".join(tickets_consumidos)
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        error_save = False
                        try:
                            for _, fila in tabla_reproceso.iterrows():
                                cursor.execute("INSERT INTO reproceso_db (id_pbo, tickets_originales_consumidos, nuevo_ticket_reprocesado, camadas_sueltas, estatus_calidad, estatus_logistica, observacion_laboratorio) VALUES (%s, %s, %s, %s, 'En Control de Calidad', 'En espera', 'Pendiente por evaluar');", (pbo_target, cadena_consumidos, fila["Nuevo Ticket Reprocesado"], int(fila["Camadas Sueltas"])))
                            for tkt in tickets_consumidos:
                                cursor.execute("UPDATE paletas_db SET estatus = 'Reprocesado' WHERE nro_ticket = %s;", (tkt,))
                            conn.commit()
                        except:
                            error_save = True
                        finally:
                            cursor.close()
                            conn.close()
                            
                        if not error_save:
                            forzar_actualizacion_red()
                            st.success("¡Lote de reproceso registrado!")
                            st.rerun()

elif "Logística" in departamento:
    st.info("📦 Permisos de Nivel: LOGÍSTICA")
    if lotes_activos_df.empty: 
        st.info("No hay casos PBO activos.")
    else:
        with st.form("form_unificado_logistica"):
            pbo_log = st.selectbox("Selecciona el PBO a gestionar:", lotes_activos_df["id_pbo"])
            nueva_ubica = st.selectbox("Reubicar lote físico completo:", UBICACIONES_LOGISTICA)
            df_rep_pbo = reprocesos_activos_df[reprocesos_activos_df["id_pbo"] == pbo_log] if not reprocesos_activos_df.empty else pd.DataFrame()
            
            if df_rep_pbo.empty:
                st.warning("Este caso aún no cuenta con paletas de reproceso.")
                tickets_log = []; nuevo_estado_log = "En espera"
            else:
                tickets_log = st.multiselect("Tickets nuevos validados en físico:", options=df_rep_pbo["nuevo_ticket_reprocesado"].unique())
                nuevo_estado_log = st.selectbox("Estatus de Verificación Logística:", ESTATUS_DICTAMEN_LOGISTICA)
            
            if st.form_submit_button("💾 Confirmar Movimiento"):
                conn = get_db_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute("UPDATE lotes_db SET ubicacion = %s WHERE id_pbo = %s;", (nueva_ubica, pbo_log))
                    for tkt in tickets_log:
                        cursor.execute("UPDATE reproceso_db SET estatus_logistica = %s WHERE nuevo_ticket_reprocesado = %s;", (nuevo_estado_log, tkt))
                    conn.commit()
                    forzar_actualizacion_red()
                    st.success("¡Inventario verificado!")
                    st.rerun()
                except Exception as e:
                    pass
                finally:
                    cursor.close()
                    conn.close()

# ==========================================
# 7. SECCIÓN DE CONSULTA, REPORTES Y TRAZABILIDAD
# ==========================================
st.divider()
st.subheader("🔍 Desglose de Piso y Auditoría")

filtro_global = st.selectbox("Filtrar paneles inferiores por caso PBO activo", ["Ver Todo"] + list(lotes_activos_df["id_pbo"]))
display_tab1, display_tab2, display_tab3 = st.tabs(["📋 Paletas Iniciales Retenidas", "🔄 Reprocesos Activos", "🏛️ Archivo de Auditoría Histórica"])

with display_tab1:
    df_f1 = paletas_activas_df if filtro_global == "Ver Todo" else paletas_activas_df[paletas_activas_df["id_pbo"] == filtro_global] if not paletas_activas_df.empty else pd.DataFrame()
    st.dataframe(df_f1, use_container_width=True, hide_index=True)

with display_tab2:
    if reprocesos_activos_df.empty: 
        st.info("No existen registros de paletas de reproceso.")
    else:
        df_f2 = reprocesos_activos_df if filtro_global == "Ver Todo" else reprocesos_activos_df[reprocesos_activos_df["id_pbo"] == filtro_global]
        st.dataframe(df_f2, use_container_width=True, hide_index=True)

with display_tab3:
    if historico_pbo_df.empty:
        st.info("El archivo histórico está vacío.")
    else:
        st.success("🏛️ Registro Inmutable de PBOs Liberados:")
        st.dataframe(historico_pbo_df, use_container_width=True, hide_index=True)
        
        st.divider()
        pbo_historico_consultar = st.selectbox("Selecciona un PBO cerrado para reconstrucción:", historico_pbo_df["id_pbo"].unique())
        
        if pbo_historico_consultar:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM historico_pbo_db WHERE id_pbo = %s;", (pbo_historico_consultar,))
            datos_historicos_macro = cursor.fetchone()
            cursor.close()
            
            df_paletas_historicas = pd.read_sql_query("SELECT * FROM historico_paletas_db WHERE id_pbo = %s", conn, params=[pbo_historico_consultar])
            df_reproceso_historico = pd.read_sql_query("SELECT * FROM historico_reproceso_db WHERE id_pbo = %s", conn, params=[pbo_historico_consultar])
            conn.close()
            
            with st.container(border=True):
                st.write(f"## 📜 REPORTE OFICIAL: {pbo_historico_consultar}")
                st.write(f"🏢 **Planta**: Empresas Polar S.A. | 📅 **Fecha**: `{datos_historicos_macro['fecha_cierre']}`")
                st.write(f"📦 **Producto**: {datos_historicos_macro['producto']} | 🏷️ **Lote**: `{datos_historicos_macro['lote']}`")
                st.write(f"📌 **Dictamen**: *{datos_historicos_macro['motivo_cierre']}*")
                st.dataframe(df_paletas_historicas, use_container_width=True, hide_index=True)