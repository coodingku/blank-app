import streamlit as st
import pandas as pd
import sqlite3
import datetime
import json
from streamlit_option_menu import option_menu
import io

# --- KONSTANTA GLOBAL ---

DB_NAME = 'staf_canteen.db'
ADMIN_BARCODE_ID = '9999' 
ADMIN_DEPARTEMEN_NAME = 'ADMIN'
TODAY_DATE = datetime.date.today().strftime("%Y-%m-%d")

# --- FUNGSI DATABASE DAN CACHE CLEARING ---

def get_db_connection():
    """Membuat dan mengembalikan koneksi database."""
    try:
        # Koneksi database dibuat tanpa st.cache_resource, 
        # namun st.cache_data akan meng-cache hasil query
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        st.error(f"Error koneksi database: {e}")
        return None

def clear_all_caches():
    """Membersihkan semua cache data setelah operasi tulis/update."""
    # Ini memastikan data yang ditampilkan selalu fresh setelah perubahan (Tulis/Update)
    st.cache_data.clear()

def setup_database():
    """Membuat tabel jika belum ada dan memastikan admin ada."""
    conn = get_db_connection()
    if conn is None:
        return
    
    try:
        cursor = conn.cursor()
        
        # 1. Tabel Departemen
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS departemen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nama_dept TEXT UNIQUE NOT NULL
            )
        ''')
        
        # 2. Tabel Menu Harian
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS menu_harian (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tanggal TEXT UNIQUE NOT NULL,
                menu_data TEXT NOT NULL
            )
        ''')

        # 3. Tabel Staf
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS staf (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                barcode_id TEXT UNIQUE NOT NULL,
                nama TEXT NOT NULL,
                departemen TEXT NOT NULL, 
                jatah_harian INTEGER NOT NULL DEFAULT 1,
                jatah_tersisa INTEGER NOT NULL DEFAULT 1
            )
        ''')

        # 4. Tabel Transaksi
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transaksi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                barcode_id TEXT NOT NULL,
                tanggal TEXT NOT NULL,
                waktu TEXT NOT NULL,
                menu TEXT NOT NULL,
                harga INTEGER NOT NULL,
                staff_nama TEXT,
                status_scan TEXT,
                FOREIGN KEY (barcode_id) REFERENCES staf(barcode_id)
            )
        ''')

        # Memastikan Admin ID ada
        cursor.execute("SELECT barcode_id FROM staf WHERE barcode_id = ?", (ADMIN_BARCODE_ID,))
        if cursor.fetchone() is None:
            cursor.execute('''
                INSERT INTO staf (barcode_id, nama, departemen, jatah_harian, jatah_tersisa) 
                VALUES (?, ?, ?, ?, ?)
            ''', (ADMIN_BARCODE_ID, 'Administrator', ADMIN_DEPARTEMEN_NAME, 999, 999))
            
        # Memastikan Admin Departemen ada
        cursor.execute("SELECT nama_dept FROM departemen WHERE nama_dept = ?", (ADMIN_DEPARTEMEN_NAME,))
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO departemen (nama_dept) VALUES (?)", (ADMIN_DEPARTEMEN_NAME,))

        conn.commit()
    except sqlite3.Error as e:
        st.error(f"Error setup database: {e}")
    finally:
        if conn:
            conn.close() 

# --- FUNGSI QUERY DATA (Baca - Menggunakan Caching) ---

@st.cache_data(ttl=300) # Cache 5 menit
def get_transactions_by_date(from_date=None, to_date=None, departemen=None, status_scan=None):
    """Mengambil semua data transaksi, opsional berdasarkan tanggal, departemen, dan status."""
    conn = get_db_connection()
    if conn is None: return pd.DataFrame()
    try:
        sql = "SELECT t.id, t.tanggal, t.waktu, t.barcode_id, t.staff_nama, s.departemen, t.menu, t.harga, t.status_scan FROM transaksi t JOIN staf s ON t.barcode_id = s.barcode_id"
        
        conditions = []
        params = []
        
        conditions.append("t.tanggal BETWEEN ? AND ?")
        params.extend([from_date, to_date])
        
        if departemen and departemen != "SEMUA DEPARTEMEN":
            conditions.append("s.departemen = ?")
            params.append(departemen)
            
        if status_scan and status_scan != "SEMUA STATUS":
            conditions.append("t.status_scan = ?")
            params.append(status_scan)
            
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
            
        sql += " ORDER BY t.tanggal DESC, t.waktu DESC"

        df = pd.read_sql_query(sql, conn, params=params)
        return df
    except Exception as e:
        st.error(f"Error mengambil data transaksi: {e}")
        return pd.DataFrame()
    finally:
        if conn:
            conn.close()

@st.cache_data(ttl=600) # Cache 10 menit
def get_staf_data(barcode_id=None):
    """
    Mengambil data staf.
    - Jika barcode_id ada: Mengembalikan dict (serializable).
    - Jika barcode_id None: Mengembalikan DataFrame (serializable).
    """
    conn = get_db_connection()
    if conn is None: return None
    try:
        sql = "SELECT barcode_id, nama, departemen, jatah_harian, jatah_tersisa FROM staf"
        params = []
        if barcode_id:
            sql += " WHERE barcode_id = ?"
            params.append(barcode_id)
            
        if barcode_id:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            row = cursor.fetchone()
            
            if row:
                # SOLUSI FIX: Konversi sqlite3.Row ke dict agar bisa di-cache
                return dict(row)
            return None 
        else:
            df = pd.read_sql_query(sql, conn, params=params)
            return df
    except Exception as e:
        st.error(f"Error mengambil data staf: {e}")
        return None
    finally:
        if conn:
            conn.close()

@st.cache_data(ttl=3600) # Cache 1 jam
def get_departemen_data():
    """Mengambil semua nama departemen."""
    conn = get_db_connection()
    if conn is None: return []
    try:
        df = pd.read_sql_query("SELECT nama_dept FROM departemen ORDER BY nama_dept", conn)
        return df['nama_dept'].tolist()
    except Exception as e:
        st.error(f"Error mengambil data departemen: {e}")
        return []
    finally:
        if conn:
            conn.close()

@st.cache_data(ttl=60) # Cache 1 menit
def get_menu_today(date_str=TODAY_DATE):
    """Mengambil menu dan harga untuk tanggal tertentu."""
    conn = get_db_connection()
    if conn is None: return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT menu_data FROM menu_harian WHERE tanggal = ?", (date_str,))
        row = cursor.fetchone()
        
        if row:
            return json.loads(row['menu_data'])
        return None
    except Exception as e:
        st.error(f"Error mengambil menu hari ini: {e}")
        return None
    finally:
        if conn:
            conn.close()

# --- FUNGSI QUERY DATA (Tulis - Memanggil clear_all_caches()) ---

def reset_jatah_harian():
    """Mengatur ulang jatah tersisa menjadi jatah harian untuk semua staf."""
    conn = get_db_connection()
    if conn is None: return False
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE staf SET jatah_tersisa = jatah_harian")
        conn.commit()
        clear_all_caches() # Clear cache setelah update
        st.success("✅ Jatah harian semua staf berhasil di-reset!")
        return True
    except sqlite3.Error as e:
        st.error(f"❌ Error saat reset jatah harian: {e}")
        return False
    finally:
        if conn:
            conn.close()

def record_transaction(barcode_id, staff_nama, menu, harga, status):
    """Mencatat transaksi dan mengurangi jatah tersisa staf."""
    conn = get_db_connection()
    if conn is None: return False
    
    tanggal = datetime.date.today().strftime("%Y-%m-%d")
    waktu = datetime.datetime.now().strftime("%H:%M:%S")
    
    try:
        cursor = conn.cursor()
        
        # 1. Catat Transaksi
        cursor.execute('''
            INSERT INTO transaksi (barcode_id, tanggal, waktu, menu, harga, staff_nama, status_scan)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (barcode_id, tanggal, waktu, menu, harga, staff_nama, status))
        
        # 2. Kurangi Jatah Tersisa (Hanya jika status sukses)
        if status == "SUKSES":
            cursor.execute("UPDATE staf SET jatah_tersisa = jatah_tersisa - 1 WHERE barcode_id = ? AND jatah_tersisa > 0", (barcode_id,))
        
        conn.commit()
        clear_all_caches() # Clear cache setelah update
        return True
    except sqlite3.Error as e:
        st.error(f"❌ Error mencatat transaksi: {e}")
        return False
    finally:
        if conn:
            conn.close()
            
def save_menu_today(date_str, menu_dict):
    """Menyimpan atau memperbarui menu harian."""
    conn = get_db_connection()
    if conn is None: return False
    try:
        menu_json = json.dumps(menu_dict)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO menu_harian (tanggal, menu_data)
            VALUES (?, ?)
        ''', (date_str, menu_json))
        
        conn.commit()
        clear_all_caches() # Clear cache setelah update
        return True
    except sqlite3.Error as e:
        st.error(f"❌ Error menyimpan menu: {e}")
        return False
    finally:
        if conn:
            conn.close()

# --- LOGIKA IMPORT CSV ---

def import_staf_from_csv(df_import):
    """Memasukkan data staf dari DataFrame ke database."""
    conn = get_db_connection()
    if conn is None: return 0, 0
    
    success_count = 0
    fail_count = 0
    
    required_cols = ['barcode_id', 'nama', 'departemen', 'jatah_harian']
    if not all(col in df_import.columns for col in required_cols):
        st.error(f"❌ Gagal: Kolom CSV tidak lengkap. Diperlukan: {', '.join(required_cols)}")
        return 0, 0
        
    cursor = conn.cursor()
    
    for index, row in df_import.iterrows():
        barcode = str(row['barcode_id']).strip()
        nama = str(row['nama']).strip()
        dept = str(row['departemen']).strip()
        try:
            jatah = int(row['jatah_harian'])
        except ValueError:
            st.warning(f"⚠️ Baris {index + 2}: Kolom jatah_harian ({row['jatah_harian']}) tidak valid. Baris dilewati.")
            fail_count += 1
            continue
            
        if not barcode or not nama or not dept or jatah <= 0:
            st.warning(f"⚠️ Baris {index + 2}: Ada data yang kosong/tidak valid. Baris dilewati.")
            fail_count += 1
            continue
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO staf (barcode_id, nama, departemen, jatah_harian, jatah_tersisa)
                VALUES (?, ?, ?, ?, ?)
            ''', (barcode, nama, dept, jatah, jatah))
            
            success_count += 1
            
            cursor.execute("INSERT OR IGNORE INTO departemen (nama_dept) VALUES (?)", (dept,))
            
        except sqlite3.IntegrityError:
             st.warning(f"⚠️ Baris {index + 2} ({barcode}): Barcode ID duplikat. Data diperbarui.")
             success_count += 1
        except Exception as e:
            st.error(f"❌ Error di Baris {index + 2} ({barcode}): {e}")
            fail_count += 1
            
    conn.commit()
    clear_all_caches() # Clear cache setelah update massal
    conn.close()
    return success_count, fail_count


# --- FUNGSI UTAMA HALAMAN ---

def authentication():
    st.title("🔐 Login Admin Kantin")
    st.write("Masukkan ID Barcode Admin untuk mengakses Laporan & Pengaturan.")

    with st.form("login_form"):
        barcode_input = st.text_input("ID Barcode Admin", max_chars=4, key="admin_barcode_input")
        submitted = st.form_submit_button("Login")

        if submitted:
            if barcode_input == ADMIN_BARCODE_ID:
                st.session_state['logged_in'] = True
                st.session_state['role'] = 'admin'
                st.success("Login berhasil!")
                st.rerun() 
            else:
                st.error("ID Barcode Admin Salah.")

def admin_page():
    st.sidebar.title("👨‍💻 Admin Panel")
    selected_menu = option_menu(
        menu_title=None,
        options=["Laporan Scan Harian", "Manajemen Staf", "Manajemen Menu & Dept", "Logout"],
        icons=["bi-bar-chart-fill", "bi-person-lines-fill", "bi-gear-fill", "bi-box-arrow-right"],
        default_index=0,
        orientation="horizontal"
    )

    st.header(f"🗃️ {selected_menu}")
    st.markdown("---")
    
    if selected_menu == "Laporan Scan Harian":
        admin_laporan_scan_harian()
    elif selected_menu == "Manajemen Staf":
        admin_manajemen_staf()
    elif selected_menu == "Manajemen Menu & Dept":
        admin_manajemen_menu_departemen()
    elif selected_menu == "Logout":
        st.session_state['logged_in'] = False
        st.session_state['role'] = 'user'
        st.success("Anda berhasil Logout.")
        st.rerun()

def admin_laporan_scan_harian():
    """Menampilkan laporan transaksi harian, dengan filter tanggal, departemen, dan status."""
    
    # Menggunakan fungsi get_departemen_data() yang sudah di-cache
    departemen_list = ["SEMUA DEPARTEMEN"] + get_departemen_data() 
    status_list = ["SEMUA STATUS", "SUKSES", "GAGAL"]

    st.subheader("Filter Laporan")
    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    with col_f1:
        from_date = st.date_input("Tanggal Awal", value=datetime.date.today(), key="laporan_from_date")
    with col_f2:
        to_date = st.date_input("Tanggal Akhir", value=datetime.date.today(), key="laporan_to_date")
    with col_f3:
        filter_dept = st.selectbox("Filter Departemen", options=departemen_list)
    with col_f4:
        filter_status = st.selectbox("Filter Status Scan", options=status_list)
    
    from_date_str = from_date.strftime("%Y-%m-%d")
    to_date_str = to_date.strftime("%Y-%m-%d")

    # Menggunakan fungsi get_transactions_by_date() yang sudah di-cache
    df_transaksi = get_transactions_by_date(
        from_date=from_date_str, 
        to_date=to_date_str, 
        departemen=filter_dept, 
        status_scan=filter_status
    )
    
    if df_transaksi.empty:
        st.warning(f"Belum ada data transaksi yang sesuai filter dari {from_date_str} sampai {to_date_str}.")
        return

    st.markdown("---")
    st.subheader("Statistik Ringkasan")
    total_sukses = df_transaksi[df_transaksi['status_scan'] == 'SUKSES'].shape[0]
    total_gagal = df_transaksi[df_transaksi['status_scan'] != 'SUKSES'].shape[0]
    total_biaya = df_transaksi[df_transaksi['status_scan'] == 'SUKSES']['harga'].sum()
    
    col_s1, col_s2, col_s3 = st.columns(3)
    col_s1.metric("Total Scan Sukses", f"{total_sukses} kali")
    col_s2.metric("Total Scan Gagal", f"{total_gagal} kali")
    col_s3.metric("Total Biaya Kantin", f"Rp {total_biaya:,.0f}")
    
    st.markdown("---")
    st.subheader("Detail Transaksi")
    
    df_transaksi = df_transaksi.rename(columns={
        'staff_nama': 'Nama Staf',
        'departemen': 'Departemen',
        'status_scan': 'Status'
    })
    
    st.dataframe(df_transaksi[['tanggal', 'waktu', 'Nama Staf', 'Departemen', 'menu', 'harga', 'Status']], use_container_width=True)
    
    csv_export = df_transaksi.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Download Data CSV",
        data=csv_export,
        file_name=f'laporan_transaksi_{from_date_str}_filtered.csv',
        mime='text/csv',
    )


def admin_manajemen_staf():
    tab1, tab2, tab3, tab4 = st.tabs(["Lihat Staf & Reset Jatah", "Tambah Staf Baru", "Edit/Hapus Staf", "📥 Impor CSV"])
    
    with tab1:
        st.subheader("Daftar Staf Aktif")
        df_staf = get_staf_data() # Menggunakan fungsi yang sudah di-cache dan aman
        
        if df_staf is None or df_staf.empty:
            st.warning("Belum ada data staf.")
        else:
            st.dataframe(df_staf[df_staf['barcode_id'] != ADMIN_BARCODE_ID], use_container_width=True)
            
        st.markdown("---")
        st.subheader("Opsi Reset Jatah")
        
        if st.button("🔄 RESET JATAH HARIAN SEMUA STAF"):
            with st.spinner("Meriset jatah..."):
                if reset_jatah_harian(): 
                    st.rerun()
                
    with tab2:
        st.subheader("Formulir Tambah Staf")
        departemen_list = get_departemen_data() 
        
        with st.form("tambah_staf_form"):
            new_barcode_id = st.text_input("ID Barcode", max_chars=10)
            new_nama = st.text_input("Nama Lengkap")
            new_dept = st.selectbox("Departemen", options=departemen_list)
            new_jatah = st.number_input("Jatah Harian (per hari)", min_value=1, value=1)
            
            submitted = st.form_submit_button("Tambah Staf")
            
            if submitted:
                if not new_barcode_id or not new_nama:
                    st.error("Semua field harus diisi.")
                else:
                    conn = get_db_connection()
                    try:
                        cursor = conn.cursor()
                        cursor.execute('''
                            INSERT INTO staf (barcode_id, nama, departemen, jatah_harian, jatah_tersisa)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (new_barcode_id, new_nama, new_dept, new_jatah, new_jatah))
                        conn.commit()
                        clear_all_caches() 
                        st.success(f"✅ Staf **{new_nama}** berhasil ditambahkan!")
                        st.rerun() 
                    except sqlite3.IntegrityError:
                        st.error("❌ Gagal: ID Barcode sudah terdaftar.")
                    except Exception as e:
                        st.error(f"❌ Error: {e}")
                    finally:
                        if conn: conn.close()
        
    with tab3:
        st.subheader("Edit atau Hapus Staf")
        
        df_staf_edit = get_staf_data() 
        if df_staf_edit is None or df_staf_edit.empty:
            st.warning("Tidak ada staf yang bisa diedit.")
            return

        staf_options = df_staf_edit[df_staf_edit['barcode_id'] != ADMIN_BARCODE_ID].apply(
            lambda row: f"{row['barcode_id']} - {row['nama']}", axis=1).tolist()

        selected_staf_info = st.selectbox("Pilih Staf untuk Diedit/Dihapus", options=["Pilih Staf..."] + staf_options)
        
        if selected_staf_info != "Pilih Staf...":
            barcode_to_edit = selected_staf_info.split(' - ')[0]
            staf_data = get_staf_data(barcode_to_edit) # Menggunakan fungsi yang sudah aman (mengembalikan dict)
            departemen_list = get_departemen_data() 
            
            if staf_data:
                
                with st.form("edit_staf_form"):
                    
                    st.text_input("ID Barcode (Tidak dapat diubah)", value=staf_data['barcode_id'], disabled=True)
                    edit_nama = st.text_input("Nama Lengkap", value=staf_data['nama'])
                    edit_dept = st.selectbox("Departemen", options=departemen_list, index=departemen_list.index(staf_data['departemen']) if staf_data['departemen'] in departemen_list else 0)
                    edit_jatah = st.number_input("Jatah Harian", min_value=1, value=staf_data['jatah_harian'])
                    
                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        update_button = st.form_submit_button("💾 Simpan Perubahan")
                    with col_e2:
                        if st.button("🗑️ Hapus Staf", key="delete_staf_button"):
                            # Logic konfirmasi hapus
                            conn = get_db_connection()
                            try:
                                cursor = conn.cursor()
                                cursor.execute("DELETE FROM staf WHERE barcode_id = ?", (barcode_to_edit,))
                                conn.commit()
                                clear_all_caches() 
                                st.success(f"🗑️ Staf **{staf_data['nama']}** berhasil dihapus!")
                                st.rerun() 
                            except Exception as e:
                                st.error(f"❌ Error saat menghapus: {e}")
                            finally:
                                if conn: conn.close()
                        
                    if update_button:
                        conn = get_db_connection()
                        try:
                            cursor = conn.cursor()
                            cursor.execute('''
                                UPDATE staf SET nama = ?, departemen = ?, jatah_harian = ?, jatah_tersisa = ? 
                                WHERE barcode_id = ?
                            ''', (edit_nama, edit_dept, edit_jatah, edit_jatah, barcode_to_edit)) 
                            conn.commit()
                            clear_all_caches() 
                            st.success(f"✅ Staf **{edit_nama}** berhasil diperbarui!")
                            st.rerun() 
                        except Exception as e:
                            st.error(f"❌ Error saat update: {e}")
                        finally:
                            if conn: conn.close()

    with tab4:
        st.subheader("Impor Data Staf Massal dari CSV")
        st.warning("Perhatian: Impor akan **memperbarui** data staf yang sudah ada jika Barcode ID-nya sama.")

        # Template Download
        template_df = pd.DataFrame({
            'barcode_id': ['1001', '1002', '1003'],
            'nama': ['Budi Santoso', 'Siti Rahma', 'Joko Susilo'],
            'departemen': ['Produksi', 'HRD', 'Gudang'],
            'jatah_harian': [1, 1, 2]
        })
        csv_template = template_df.to_csv(index=False).encode('utf-8')
        
        st.download_button(
            label="⬇️ Download Contoh CSV Template",
            data=csv_template,
            file_name='template_staf_import.csv',
            mime='text/csv',
        )
        st.markdown("---")
        
        uploaded_file = st.file_uploader("Upload File CSV Staf Baru", type=['csv'])

        if uploaded_file is not None:
            try:
                df_import = pd.read_csv(io.StringIO(uploaded_file.getvalue().decode("utf-8")))
                st.write("Pratinjau Data yang Diimpor:")
                st.dataframe(df_import, use_container_width=True)

                if st.button("🚀 Proses Impor Data"):
                    with st.spinner("Memproses impor dan validasi data..."):
                        success_count, fail_count = import_staf_from_csv(df_import) 
                        
                        st.success(f"🎉 Impor Selesai! **{success_count}** Staf berhasil dimasukkan/diperbarui.")
                        if fail_count > 0:
                            st.error(f"⚠️ **{fail_count}** Baris Gagal diproses (cek log warning di atas).")
                        st.rerun() 
                        
            except Exception as e:
                st.error(f"❌ Error saat membaca atau memproses file CSV: {e}")
                
                

def admin_manajemen_menu_departemen():
    tab1, tab2 = st.tabs(["Manajemen Menu Harian", "Manajemen Departemen"])
    
    with tab1:
        st.subheader("Atur Menu dan Harga Hari Ini")
        
        menu_data = get_menu_today() # Menggunakan fungsi yang sudah di-cache
        initial_menu = menu_data['menu'] if menu_data else "Nasi Goreng"
        initial_harga = menu_data['harga'] if menu_data else 15000

        with st.form("form_menu_harian"):
            menu_input = st.text_input("Nama Menu", value=initial_menu)
            harga_input = st.number_input("Harga Menu (Rp)", min_value=100, value=initial_harga, step=100)
            
            submitted = st.form_submit_button("Simpan Menu Hari Ini")
            
            if submitted:
                if not menu_input or harga_input <= 0:
                    st.error("Menu dan Harga harus valid.")
                else:
                    menu_dict = {"menu": menu_input, "harga": int(harga_input)}
                    if save_menu_today(TODAY_DATE, menu_dict): 
                        st.success(f"✅ Menu hari ini ({TODAY_DATE}) berhasil diatur: **{menu_input}** (Rp {harga_input:,.0f})")
                        st.rerun() 

        st.info(f"Menu yang aktif hari ini ({TODAY_DATE}): **{menu_data['menu'] if menu_data else 'BELUM DIATUR'}** dengan harga **Rp {menu_data['harga'] if menu_data else 0:,.0f}**")

    with tab2:
        st.subheader("Tambah Departemen Baru")
        
        with st.form("form_tambah_dept"):
            new_dept_name = st.text_input("Nama Departemen Baru")
            submitted_dept = st.form_submit_button("Tambah Departemen")
            
            if submitted_dept:
                if not new_dept_name:
                    st.error("Nama departemen tidak boleh kosong.")
                else:
                    conn = get_db_connection()
                    try:
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO departemen (nama_dept) VALUES (?)", (new_dept_name,))
                        conn.commit()
                        clear_all_caches() 
                        st.success(f"✅ Departemen **{new_dept_name}** berhasil ditambahkan!")
                        st.rerun() 
                    except sqlite3.IntegrityError:
                        st.error("❌ Gagal: Departemen sudah terdaftar.")
                    except Exception as e:
                        st.error(f"❌ Error: {e}")
                    finally:
                        if conn: conn.close()

        st.markdown("---")
        st.subheader("Daftar Departemen Aktif")
        st.dataframe(pd.DataFrame(get_departemen_data(), columns=['Nama Departemen']), use_container_width=True) 

def scan_page():
    """Halaman utama pemindaian barcode."""
    st.title("🍽️ Sistem Kantin Cerdas")
    
    menu_today = get_menu_today() 
    
    if not menu_today:
        st.warning(f"❌ Menu harian untuk hari ini ({TODAY_DATE}) belum diatur oleh Admin. Pemindaian ditangguhkan.")
        st.info("Silakan login sebagai Admin untuk mengatur menu di bagian 'Manajemen Menu & Dept'.")
        return
        
    st.info(f"Menu Hari Ini: **{menu_today['menu']}** (Rp {menu_today['harga']:,.0f})")
    st.markdown("---")
    
    with st.form("scan_form", clear_on_submit=True):
        barcode_input = st.text_input("SCAN BARCODE ID / KETIK MANUAL", max_chars=10, key="barcode_scan_input")
        submitted = st.form_submit_button("Proses Scan", type="primary") 

    if submitted and barcode_input:
        
        barcode_id_to_process = barcode_input
        
        st.subheader("Hasil Pemindaian")
        
        staf = get_staf_data(barcode_id_to_process) # Menggunakan fungsi yang sudah aman (mengembalikan dict)
        
        if staf is None:
            status = "GAGAL"
            record_transaction(barcode_id_to_process, "N/A", menu_today['menu'], menu_today['harga'], status)
            st.error("❌ GAGAL: ID Barcode tidak terdaftar.")
            
        elif staf['barcode_id'] == ADMIN_BARCODE_ID:
            status = "GAGAL"
            record_transaction(barcode_id_to_process, staf['nama'], menu_today['menu'], menu_today['harga'], status)
            st.warning("❌ GAGAL: ID Admin tidak dapat digunakan untuk transaksi kantin.")
            
        elif staf['jatah_tersisa'] <= 0:
            status = "GAGAL"
            record_transaction(barcode_id_to_process, staf['nama'], menu_today['menu'], menu_today['harga'], status)
            st.warning(f"⚠️ GAGAL: Jatah makan harian Sdr. **{staf['nama']}** telah habis.")
            
        else:
            status = "SUKSES"
            # Fungsi ini akan mencatat dan mengurangi jatah, lalu memanggil clear_all_caches()
            record_transaction(barcode_id_to_process, staf['nama'], menu_today['menu'], menu_today['harga'], status)
            
            st.success(f"✅ SUKSES!")
            st.balloons()
            
            # Panggil get_staf_data lagi untuk mendapatkan sisa jatah yang sudah terupdate (karena cache sudah di-clear)
            staf_after_scan = get_staf_data(barcode_id_to_process) 
            
            st.metric(label="Nama Staf", value=staf_after_scan['nama'])
            st.metric(label="Departemen", value=staf_after_scan['departemen'])
            st.metric(label="Menu", value=menu_today['menu'])
            st.metric(label="Harga", value=f"Rp {menu_today['harga']:,.0f}")
            st.info(f"Sisa Jatah: **{staf_after_scan['jatah_tersisa']}** dari {staf_after_scan['jatah_harian']} kali")
            

# --- FUNGSI UTAMA APLIKASI ---

def main():
    """Mengatur tampilan utama, routing, dan inisialisasi database."""
    
    st.set_page_config(
        page_title="Sistem Kantin Staf",
        page_icon="🍽️",
        layout="wide",
        initial_sidebar_state="collapsed"
    )
    
    # Inisialisasi Session State
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        st.session_state['role'] = 'user'
        
    # --- Inisialisasi Database (Hanya sekali per sesi) ---
    if 'db_initialized' not in st.session_state:
        setup_database()
        st.session_state['db_initialized'] = True
    
    # --- Sidebar Menu ---
    with st.sidebar:
        st.title("Navigasi")
        if st.session_state['logged_in']:
            if st.button("Beralih ke Scan Kantin"):
                st.session_state['logged_in'] = False
                st.session_state['role'] = 'user'
                st.rerun() 
            st.button("Logout", on_click=lambda: st.session_state.update({'logged_in': False, 'role': 'user'}))
        else:
            if st.button("Login Admin"):
                st.session_state['logged_in'] = False 
                st.session_state['role'] = 'login'


    # --- Routing Halaman ---
    if st.session_state['logged_in'] and st.session_state['role'] == 'admin':
        admin_page()
    elif st.session_state['role'] == 'login':
        authentication()
    else:
        scan_page()

if __name__ == '__main__':
    main()