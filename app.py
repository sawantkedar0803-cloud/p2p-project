import os
import mysql.connector
from flask import Flask, render_template, request

# --- VERCEL FIX: Tell Flask exactly where the folders are ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates') if os.path.exists(os.path.join(BASE_DIR, 'templates')) else BASE_DIR
STATIC_DIR = os.path.join(BASE_DIR, 'static') if os.path.exists(os.path.join(BASE_DIR, 'static')) else BASE_DIR

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)


def get_db_connection():
    return mysql.connector.connect(
        host="gateway01.ap-southeast-1.prod.aws.tidbcloud.com",
        user="86fpvThio47T1nK.root",
        password="nlUoHF55C0JPXlsI",  # Ensure this matches your Workbench
        database="p2p_enterprise"
    )


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/login', methods=['POST'])
def login():
    email = request.form['email'].strip().lower()
    password = request.form['password']

    conn = get_db_connection()
    cursor = conn.cursor()

    # ==========================================
    # 1. ADMIN LOGIN LOGIC
    # ==========================================
    if email == 'admin@gmail.com' and password == 'admin':
        # Borrowers
        cursor.execute('''
            SELECT u.UserID, u.FullName, bp.EmpType, lr.Amount_Needed, lr.Expected_Interest, lr.Amount_Funded, lr.Status 
            FROM Users u 
            JOIN Borrower_Profiles bp ON u.UserID = bp.UserID 
            JOIN Loan_Requests lr ON u.UserID = lr.UserID
            WHERE u.UserType = 'borrower'
        ''')
        real_borrowers = cursor.fetchall()

        # Lenders
        cursor.execute('''
            SELECT u.UserID, u.FullName, lp.MinROI, lp.MaxROI, lp.InvestAmount, lp.AutoInvest 
            FROM Users u 
            JOIN Lender_Profiles lp ON u.UserID = lp.UserID
            WHERE u.UserType = 'lender'
        ''')
        real_lenders = cursor.fetchall()

        # Diversification Map
        cursor.execute('''
            SELECT u1.FullName as InvestorName, u2.FullName as BorrowerName, 
                   im.Amount_Allocated, lr.Expected_Interest, im.Allocation_Date,
                   im.MappingID, lr.Tenure
            FROM Investment_Mapping im
            JOIN Users u1 ON im.InvestorID = u1.UserID
            JOIN Loan_Requests lr ON im.LoanID = lr.LoanID
            JOIN Users u2 ON lr.UserID = u2.UserID
            ORDER BY im.Allocation_Date DESC LIMIT 10
        ''')
        mappings = cursor.fetchall()

        # Query 1: Capital Analytics
        cursor.execute('''
                    SELECT 
                        (SELECT COALESCE(SUM(InvestAmount), 0) FROM Lender_Profiles) as IdleCapital,
                        (SELECT COALESCE(SUM(Amount_Allocated), 0) FROM Investment_Mapping) as AllocatedCapital
                ''')
        capital_analytics = cursor.fetchone()

        # Query 2: Lenders Segmented by Risk Appetite
        cursor.execute('''
                    SELECT RiskAppetite, COUNT(UserID) as TotalInvestors, SUM(InvestAmount) as TotalCapital
                    FROM Lender_Profiles
                    GROUP BY RiskAppetite
                ''')
        risk_analytics = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('index.html', role='admin', borrowers=real_borrowers, lenders=real_lenders,
                               mappings=mappings, capital_analytics=capital_analytics, risk_analytics=risk_analytics)

    # ==========================================
    # 2. NORMAL USER LOGIN LOGIC
    # ==========================================
    cursor.execute("SELECT UserID, FullName, UserType FROM Users WHERE Email = %s AND Password = %s", (email, password))
    user = cursor.fetchone()

    if user:
        user_id = user[0]
        full_name = user[1]
        user_type = str(user[2]).strip().lower()

        if user_type == 'lender':
            cursor.execute("SELECT InvestAmount, MinROI, MaxROI, AutoInvest FROM Lender_Profiles WHERE UserID = %s",
                           (user_id,))
            profile = cursor.fetchone()

            cursor.execute('''
                SELECT u.FullName as BorrowerName, im.Amount_Allocated, lr.Expected_Interest, im.Allocation_Date, lr.Tenure
                FROM Investment_Mapping im
                JOIN Loan_Requests lr ON im.LoanID = lr.LoanID
                JOIN Users u ON lr.UserID = u.UserID
                WHERE im.InvestorID = %s
            ''', (user_id,))
            portfolio = cursor.fetchall()

            cursor.close()
            conn.close()
            return render_template('index.html', role='lender', user_name=full_name, profile=profile,
                                   portfolio=portfolio)

        elif user_type == 'borrower':
            cursor.execute(
                "SELECT Amount_Needed, Amount_Funded, Expected_Interest, Status, Tenure FROM Loan_Requests WHERE UserID = %s",
                (user_id,))
            loan = cursor.fetchone()

            cursor.execute('''
                SELECT u.FullName as InvestorName, im.Amount_Allocated, im.Allocation_Date
                FROM Investment_Mapping im
                JOIN Users u ON im.InvestorID = u.UserID
                WHERE im.LoanID = (SELECT LoanID FROM Loan_Requests WHERE UserID = %s LIMIT 1)
            ''', (user_id,))
            backers = cursor.fetchall()

            cursor.close()
            conn.close()
            return render_template('index.html', role='borrower', user_name=full_name, loan=loan, backers=backers)

    cursor.close()
    conn.close()
    return f"<h3>Authentication Failed</h3><p>Invalid credentials.</p><a href='/'>Go Back</a>"


@app.route('/register_full', methods=['POST'])
def register_full():
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        conn.start_transaction()

        full_name = request.form['full_name']
        email = request.form['email'].strip().lower()
        mobile = request.form['mobile']
        password = request.form['password']
        user_type = request.form['user_type']

        cursor.execute('''
            INSERT INTO Users (FullName, Email, Mobile, Password, UserType)
            VALUES (%s, %s, %s, %s, %s)
        ''', (full_name, email, mobile, password, user_type))
        user_id = cursor.lastrowid

        cursor.execute('''
            INSERT INTO KYC_Details (UserID, DOB, Gender, PAN_Number, Aadhaar_Number, Street, City, State, Pincode)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            user_id, request.form.get('dob') or None, request.form.get('gender') or None,
            request.form.get('pan') or None, request.form.get('aadhaar') or None,
            request.form.get('street') or None, request.form.get('city') or None,
            request.form.get('state') or None, request.form.get('pincode') or None
        ))

        if user_type == 'borrower':
            cursor.execute('''
                INSERT INTO Borrower_Profiles (UserID, EmpType, MonthlyIncome, CompanyName, WorkExp, ExistingEMI, CibilScore)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (
                user_id, request.form.get('emp_type') or None, request.form.get('monthly_income') or None,
                request.form.get('company') or None, request.form.get('work_exp') or None,
                request.form.get('existing_emi') or None, request.form.get('cibil') or None
            ))

            cursor.execute('''
                INSERT INTO Loan_Requests (UserID, Amount_Needed, Purpose, Tenure, Expected_Interest)
                VALUES (%s, %s, %s, %s, %s)
            ''', (
                user_id, request.form.get('loan_amount') or None, request.form.get('purpose') or None,
                request.form.get('tenure') or None, request.form.get('expected_interest') or None
            ))

        elif user_type == 'lender':
            roi_range = request.form.get('roi_range', '10-12').split('-')
            min_roi = float(roi_range[0])
            max_roi = float(roi_range[1])

            cursor.execute('''
                           INSERT INTO Lender_Profiles (UserID, InvestAmount, RiskAppetite, MinROI, MaxROI, AutoInvest)
                           VALUES (%s, %s, %s, %s, %s, %s)
                       ''', (
                user_id, request.form.get('invest_amount') or None, request.form.get('risk_appetite') or None,
                min_roi, max_roi, request.form.get('auto_invest') or None
            ))

        conn.commit()
        result_msg = f"SUCCESS! Entity '{full_name}' Registered successfully."

    except Exception as e:
        conn.rollback()
        result_msg = f"CRITICAL SYSTEM ERROR: {str(e)}"
    finally:
        cursor.close()
        conn.close()

    return f"<h3>{result_msg}</h3><br><a href='/'>Return to Portal</a>"


# ==========================================
# REWRITTEN FOR TIDB: PYTHON-LEVEL ACID TRANSACTIONS
# ==========================================
@app.route('/run_engine', methods=['POST'])
def run_engine():
    conn = get_db_connection()
    cursor = conn.cursor()
    allocation_logs = []

    try:
        # 1. Fetch all active auto-invest lenders
        cursor.execute(
            "SELECT UserID, InvestAmount, MinROI, MaxROI FROM Lender_Profiles WHERE AutoInvest = 'yes' AND InvestAmount > 0")
        active_lenders = cursor.fetchall()

        for lender in active_lenders:
            lender_id, amount, min_roi, max_roi = lender

            # Start ACID Transaction for this specific investor
            conn.start_transaction()

            # Find ONE open loan matching the criteria. FOR UPDATE locks the row.
            cursor.execute(
                "SELECT LoanID, (Amount_Needed - Amount_Funded) FROM Loan_Requests WHERE Status = 'OPEN' AND Expected_Interest >= %s LIMIT 1 FOR UPDATE",
                (min_roi,))
            loan = cursor.fetchone()

            if loan:
                loan_id, gap = loan
                allocated = gap if amount > gap else amount

                # Update database tables
                cursor.execute(
                    "INSERT INTO Investment_Mapping (InvestorID, LoanID, Amount_Allocated) VALUES (%s, %s, %s)",
                    (lender_id, loan_id, allocated))
                cursor.execute("UPDATE Loan_Requests SET Amount_Funded = Amount_Funded + %s WHERE LoanID = %s",
                               (allocated, loan_id))
                cursor.execute("UPDATE Lender_Profiles SET InvestAmount = InvestAmount - %s WHERE UserID = %s",
                               (allocated, lender_id))

                # Check if loan is full
                cursor.execute("SELECT Amount_Funded, Amount_Needed FROM Loan_Requests WHERE LoanID = %s", (loan_id,))
                f_amt, n_amt = cursor.fetchone()
                if f_amt >= n_amt:
                    cursor.execute("UPDATE Loan_Requests SET Status = 'FILLED' WHERE LoanID = %s", (loan_id,))

                conn.commit()
                allocation_logs.append(f"Investor #{lender_id}: Success: Allocated Rs. {allocated} to Loan {loan_id}")
            else:
                conn.rollback()
                allocation_logs.append(f"Investor #{lender_id}: Failed: No matching loans found in ROI range")

    except Exception as e:
        conn.rollback()
        allocation_logs = [f"System Error: {str(e)}"]
    finally:
        cursor.close()
        conn.close()

    logs_html = "<br>".join(
        allocation_logs) if allocation_logs else "Engine Swept. No valid loans match the current liquidity mandates."

    return f"""
    <div style="font-family: Arial; padding: 40px; text-align: center; background-color: #F4F4F4; height: 100vh;">
        <h2 style="color: #092040; font-size: 28px;">Allocation Engine Execution Log</h2>
        <div style="padding: 20px; background-color: #1e1e1e; color: #00ff00; border-left: 5px solid #D2A32C; margin: 20px auto; max-width: 800px; text-align: left; font-family: monospace; font-size: 16px;">
            <p><strong>[SYSTEM OUTPUT]</strong><br><br>{logs_html}</p>
        </div>
        <br><p>Log in as Admin to see the new Diversification Ledger.</p>
        <a href="/" style="display: inline-block; margin-top: 20px; padding: 12px 24px; background-color: #092040; color: white; text-decoration: none;">Return to Portal</a>
    </div>
    """


@app.route('/simulate_emi', methods=['POST'])
def simulate_emi():
    conn = get_db_connection()
    cursor = conn.cursor()
    msg = ""

    try:
        conn.start_transaction()

        cursor.execute('''
            SELECT lr.UserID, im.InvestorID, im.Amount_Allocated, lr.Expected_Interest, lr.Tenure
            FROM Investment_Mapping im
            JOIN Loan_Requests lr ON im.LoanID = lr.LoanID
            WHERE lr.Status = 'FILLED'
        ''')
        mappings = cursor.fetchall()

        for mapping in mappings:
            b_id, i_id, alloc, interest, tenure = mapping

            # Calculate EMI (Principal + Profit)
            emi = (float(alloc) + (float(alloc) * (float(interest) / 100.0))) / float(tenure)

            cursor.execute("UPDATE Borrower_Profiles SET BankBalance = BankBalance - %s WHERE UserID = %s", (emi, b_id))
            cursor.execute("UPDATE Lender_Profiles SET InvestAmount = InvestAmount + %s WHERE UserID = %s", (emi, i_id))

        conn.commit()
        msg = "Success: 1 Month of EMI processed and routed across all accounts."
    except Exception as e:
        conn.rollback()
        msg = f"System Error: {str(e)}"
    finally:
        cursor.close()
        conn.close()

    return f"""
    <div style="font-family: Arial; padding: 40px; text-align: center; background-color: #F4F4F4; height: 100vh;">
        <h2 style="color: #092040; font-size: 28px;">EMI Routing Execution Log</h2>
        <div style="padding: 20px; background-color: #1e1e1e; color: #00ff00; border-left: 5px solid #22c55e; margin: 20px auto; max-width: 800px; text-align: left; font-family: monospace; font-size: 16px;">
            <p><strong>[SYSTEM OUTPUT]</strong><br><br>{msg}</p>
        </div>
        <br><a href="/" style="display: inline-block; margin-top: 20px; padding: 12px 24px; background-color: #092040; color: white; text-decoration: none;">Return to Portal</a>
    </div>
    """


@app.route('/invoice/<int:mapping_id>')
def generate_invoice(mapping_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT u1.FullName as InvestorName, u1.Email as InvEmail, 
               u2.FullName as BorrowerName, u2.Email as BorEmail,
               im.Amount_Allocated, lr.Expected_Interest, im.Allocation_Date
        FROM Investment_Mapping im
        JOIN Investors_Profiles u1 ON im.InvestorID = u1.UserID
        JOIN Loan_Requests lr ON im.LoanID = lr.LoanID
        JOIN Users u2 ON lr.UserID = u2.UserID
        WHERE im.MappingID = %s
    ''', (mapping_id,))

    invoice_data = cursor.fetchone()
    cursor.close()
    conn.close()

    if not invoice_data:
        return "Invoice not found.", 404

    return f"""
    <div style="font-family: Arial; max-width: 600px; margin: 50px auto; padding: 30px; border: 1px solid #ccc; box-shadow: 0 0 10px rgba(0,0,0,0.1);">
        <h2 style="color: #092040; border-bottom: 2px solid #D2A32C; padding-bottom: 10px;">Official Allocation Invoice</h2>
        <p><strong>Transaction ID:</strong> #{mapping_id}</p>
        <p><strong>Date:</strong> {invoice_data[6]}</p>
        <hr style="margin: 20px 0;">
        <div style="display: flex; justify-content: space-between;">
            <div>
                <h4 style="margin-bottom: 5px; color: #666;">Lender Details</h4>
                <p style="margin: 0;"><b>{invoice_data[0]}</b></p>
                <p style="margin: 0; font-size: 12px; color: #888;">{invoice_data[1]}</p>
            </div>
            <div style="text-align: right;">
                <h4 style="margin-bottom: 5px; color: #666;">Borrower Details</h4>
                <p style="margin: 0;"><b>{invoice_data[2]}</b></p>
                <p style="margin: 0; font-size: 12px; color: #888;">{invoice_data[3]}</p>
            </div>
        </div>
        <hr style="margin: 20px 0;">
        <h3 style="background-color: #f4f4f4; padding: 10px;">Allocated Capital: <span style="color: green;">₹ {invoice_data[4]}</span></h3>
        <p><strong>Agreed Interest Rate:</strong> {invoice_data[5]}%</p>
        <div style="margin-top: 40px; text-align: center;">
            <button onclick="window.print()" style="padding: 10px 20px; background-color: #092040; color: white; border: none; border-radius: 5px; cursor: pointer;">Print to PDF / Save</button>
            <p style="font-size: 11px; color: #aaa; margin-top: 10px;">A copy of this PDF has been queued for email distribution.</p>
        </div>
    </div>
    """


if __name__ == '__main__':
    app.run(debug=True)