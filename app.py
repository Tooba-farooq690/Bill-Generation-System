from fastapi import FastAPI, Request, Form
from fastapi.middleware.cors import CORSMiddleware 
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from datetime import datetime


# import datetime
import os
import logging
import oracledb
import uvicorn


d = os.environ.get("ORACLE_HOME")  
oracledb.init_oracle_client(lib_dir=d)  


user_name = os.environ.get("DB_USERNAME")
user_pswd = os.environ.get("DB_PASSWORD")
db_alias = os.environ.get("DB_ALIAS")

connection = oracledb.connect(
    user=user_name,
    password=user_pswd,
    dsn=db_alias
)
print("Database connected")

# FastAPI app setup
app = FastAPI()

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)

origins = ['*']

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


# -----------------------------
# Database Connection and Query Execution
# -----------------------------
def get_db_connection():
    return oracledb.connect(user=user_name, password=user_pswd, dsn=db_alias)


def execute_query(query, params=None):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(query, params if params else {})
        result = cursor.fetchall()
        cursor.close()
        conn.close()
        logger.debug(f"Query result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error executing query: {e}")
        return None



# -----------------------------
# API Endpoints
# -----------------------------

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Bill payment page
@app.get("/bill-payment", response_class=HTMLResponse)
async def get_bill_payment(request: Request):
    return templates.TemplateResponse("bill_payment.html", {"request": request})

# Bill generation page
@app.get("/bill-retrieval", response_class=HTMLResponse)
async def get_bill_retrieval(request: Request):
    return templates.TemplateResponse("bill_retrieval.html", {"request": request})

# Adjustments page
@app.get("/bill-adjustments", response_class=HTMLResponse)
async def get_bill_adjustment(request: Request):
    return templates.TemplateResponse("bill_adjustment.html", {"request": request})





# ---------- POST methods for the pages ----------


@app.post("/bill-payment", response_class=HTMLResponse)
async def post_bill_payment(request: Request, bill_id: int = Form(...), amount: float = Form(...), payment_method_id: int = Form(...)):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            INSERT INTO PaymentDetails (BillID, PaymentDate, PaymentMethodID, AmountPaid, PaymentStatus)
            VALUES (:bill_id, :payment_date, :payment_method_id, :amount_paid, 'Pending')
        """, bill_id=bill_id, payment_date=datetime.now(), payment_method_id=payment_method_id, amount_paid=amount)
        connection.commit()

        cursor.execute("""
            SELECT PaymentMethodDescription
            FROM PaymentMethods
            WHERE PaymentMethodID = :payment_method_id
        """, payment_method_id=payment_method_id)
        payment_method_description = cursor.fetchone()[0]

        cursor.execute("""
            SELECT TotalAmount_AfterDueDate
            FROM Bill
            WHERE BillID = :bill_id
        """, bill_id=bill_id)
        bill_amount = cursor.fetchone()[0]
        outstanding_amount = bill_amount - amount

        payment_status = "Fully Paid" if outstanding_amount <= 0 else "Partially Paid"

        cursor.execute("""
            UPDATE PaymentDetails
            SET PaymentStatus = :payment_status
            WHERE BillID = :bill_id AND PaymentDate = :payment_date
        """, payment_status=payment_status, bill_id=bill_id, payment_date=datetime.now())
        connection.commit()

        payment_details = {
            "bill_id": bill_id,
            "amount": amount,
            "payment_method_id": payment_method_id,
            "payment_method_description": payment_method_description,
            "payment_date": datetime.now(),
            "payment_status": payment_status,
            "outstanding_amount": outstanding_amount
        }

        return templates.TemplateResponse("payment_receipt.html", {"request": request, "payment_details": payment_details})

    except Exception as e:
        print(f"Error: {e}")
        connection.rollback()
        return JSONResponse(status_code=400, content={"message": "Error processing payment."})
    finally:
        cursor.close()
        connection.close()











@app.post("/bill-retrieval", response_class=HTMLResponse)
async def post_bill_retrieval(
    request: Request,
    customer_id: str = Form(...),
    connection_id: str = Form(...),
    month: str = Form(...),
    year: str = Form(...),
):
    month, year = int(month), int(year)

    cursor = connection.cursor()

    try:
        query_con_details = """
        SELECT D.DivisionName, D.SubDivName, C.InstallationDate, C.MeterType
        FROM DivInfo D 
        JOIN Connections C 
        ON C.DivisionID = D.DivisionID AND C.SubDivID = D.SubDivID
        WHERE C.ConnectionID = :connection_id
        """
        cursor.execute(query_con_details, {"connection_id": connection_id})
        con_details = cursor.fetchone()
        if not con_details:
            return {"message": "Error retrieving connection details."}

        query_cus_details = """
        SELECT C.FirstName, C.LastName, C.Address, C.PhoneNumber, C.Email, C.CustomerType
        FROM Customers C
        WHERE C.CustomerID = :customer_id
        """
        cursor.execute(query_cus_details, {"customer_id": customer_id})
        cust_details = cursor.fetchone()
        if not cust_details:
            return {"message": "Error retrieving customer details."}


        query_bill_dets = """
        SELECT B.BillIssueDate, B.DueDate, B.TotalAmount_BeforeDueDate, B.TotalAmount_AfterDueDate
        FROM Bill B
        WHERE B.ConnectionID = :connection_id
        """
        cursor.execute(query_bill_dets, {"connection_id": connection_id})
        bill_info = cursor.fetchone()
        if not bill_info:
            return {"message": "Error retrieving bill details."}

        query_tariff = """
        SELECT T.TarrifDescription, T.MinUnit, T.RatePerUnit, T.MinAmount
        FROM Tariff T JOIN Connections C ON T.ConnectionTypeCode = C.ConnectionTypeCode
        WHERE C.ConnectionID = :connection_id
        """
        cursor.execute(query_tariff, {"connection_id": connection_id})
        tariffs_list = []
        for row in cursor.fetchall():
            tariffs_list.append({
                "name": row[0],
                "units": row[1],
                "rate": row[2],
                "amount": row[3],
            })

        query_taxes = """
        SELECT T.Rate, T.TaxType 
        FROM TaxRates T JOIN Connections C ON T.ConnectionTypeCode = C.ConnectionTypeCode
        WHERE C.ConnectionID = :connection_id
        """
        cursor.execute(query_taxes, {"connection_id": connection_id})
        tax_list = []
        for row in cursor.fetchall():
            tax_list.append({
                "name": row[1],
                "amount": row[0] * bill_info[2],  
            })

        query_subsidy = """
        SELECT SubsidyCode, ProviderName, RatePerUnit
        FROM Subsidy 
        JOIN SubsidyProvider ON Subsidy.ProviderID = SubsidyProvider.ProviderID 
        JOIN Connections ON Subsidy.ConnectionTypeCode = Connections.ConnectionTypeCode
        WHERE Connections.ConnectionID = :connection_id
        """
        cursor.execute(query_subsidy, {"connection_id": connection_id})
        subsidy_list = []
        for row in cursor.fetchall():
            subsidy_list.append({
                "name": row[0],
                "provider_name": row[1],
                "rate_per_unit": row[2],
            })

        query_fix = """
        SELECT F.FixedFee, F.FixedChargeType
        FROM FixedCharges F 
        JOIN Connections C ON F.ConnectionTypeCode = C.ConnectionTypeCode
        WHERE C.ConnectionID = :connection_id
        """
        cursor.execute(query_fix, {"connection_id": connection_id})
        fixed_chrg_list = []
        for row in cursor.fetchall():
            fixed_chrg_list.append({
                "name": row[1],
                "amount": row[0],
            })



        previous_bills_query = """
        SELECT BillingMonth, BillingYear, TotalAmount_BeforeDueDate, DueDate, PaymentStatus
        FROM Bill
        JOIN PaymentDetails ON Bill.BillID = PaymentDetails.BillID
        WHERE ConnectionID = :connection_id
        ORDER BY BillIssueDate DESC
        """
        cursor.execute(previous_bills_query, {"connection_id": connection_id})
        previous_bills = []
        for row in cursor.fetchmany(10):  # Fetch only the latest 10 bills
            previous_bills.append({
                "month": f"{row[0]}-{row[1]}",
                "amount": row[2],
                "due_date": row[3],
                "status": row[4],
            })

        imp_peak_units = cursor.callfunc('fun_compute_ImportPeakUnits', oracledb.NUMBER, [connection_id, month, year])
        imp_off_peak_units = cursor.callfunc('fun_compute_ImportOffPeakUnits', oracledb.NUMBER, [connection_id, month, year])
        exp_off_peak_units = cursor.callfunc('fun_compute_ExportOffPeakUnits', oracledb.NUMBER, [connection_id, month, year])
        netoffpeak_units = imp_off_peak_units - exp_off_peak_units

        peak_amount = cursor.callfunc('fun_compute_PeakAmount', oracledb.NUMBER, [connection_id, month, year, bill_info[0]])
        offpeak_amount = cursor.callfunc('fun_compute_OffPeakAmount', oracledb.NUMBER, [connection_id, month, year, bill_info[0]])
        arrears = cursor.callfunc('fun_compute_Arrears', oracledb.NUMBER, [connection_id, month, year, bill_info[0]])
        fixed_fee = cursor.callfunc('fun_compute_FixedFee', oracledb.NUMBER, [connection_id, month, year, bill_info[0]])
        tax_amount = cursor.callfunc('fun_compute_TaxAmount', oracledb.NUMBER, [connection_id, month, year, bill_info[0], peak_amount, offpeak_amount])

        bill_details = {
            "customer_id": customer_id,
            "connection_id": connection_id,
            "customer_name": f"{cust_details[0]} {cust_details[1]}",
            "customer_address": cust_details[2],
            "customer_phone": cust_details[3],
            "customer_email": cust_details[4],
            "connection_type": cust_details[5],
            "division": con_details[0],
            "subdivision": con_details[1],
            "installation_date": con_details[2],
            "meter_type": con_details[3],
            "issue_date": bill_info[0],
            "net_peak_units": imp_peak_units,
            "net_off_peak_units": netoffpeak_units,
            "bill_amount": bill_info[2],
            "due_date": bill_info[1],
            "amount_after_due_date": bill_info[3],
            "month": month,
            "arrears_amount": arrears,
            "fixed_fee_amount": fixed_fee,
            "tax_amount": tax_amount,
            "tariffs": tariffs_list,
            "taxes": tax_list,
            "subsidies": subsidy_list,
            "fixed_fee": fixed_chrg_list,
            "bills_prev": previous_bills,
        }

        return templates.TemplateResponse("bill_details.html", {"request": request, "bill_details": bill_details})

    except Exception as e:
        return {"message": f"An error occurred: {str(e)}"}
    finally:
        cursor.close()
        connection.close()









@app.post("/bill-adjustment", response_class=HTMLResponse)
async def post_bill_adjustment(
    request: Request,
    bill_id: int = Form(...),
    officer_name: str = Form(...),
    officer_designation: str = Form(...),
    original_bill_amount: float = Form(...),
    adjustment_amount: float = Form(...),
    adjustment_reason: str = Form(...),
):
    adjustment_id = str(145)

    adjustment_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    adjusted_bill_amount = original_bill_amount - adjustment_amount

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        insert_query = """
        INSERT INTO BillAdjustments 
        (AdjustmentID, BillID, AdjustmentAmount, AdjustmentReason, AdjustmentDate, 
        OfficerName, OfficerDesignation, OriginalBillAmount)
        VALUES 
        (:adjustment_id, :bill_id, :adjustment_amount, :adjustment_reason, 
        TO_DATE(:adjustment_date, 'YYYY-MM-DD HH24:MI:SS'), :officer_name, :officer_designation, :original_bill_amount)
        """

        cursor.execute(
            insert_query,
            {
                "adjustment_id": adjustment_id,
                "bill_id": bill_id,
                "adjustment_amount": adjustment_amount,
                "adjustment_reason": adjustment_reason,
                "adjustment_date": adjustment_date,
                "officer_name": officer_name,
                "officer_designation": officer_designation,
                "original_bill_amount": original_bill_amount,
            }
        )
        connection.commit()

        adjustment_details = {
            "adjustment_id": adjustment_id,
            "bill_id": bill_id,
            "officer_name": officer_name,
            "officer_designation": officer_designation,
            "original_bill_amount": original_bill_amount,
            "adjustment_amount": adjustment_amount,
            "adjusted_bill_amount": adjusted_bill_amount,
            "adjustment_reason": adjustment_reason,
            "adjustment_date": adjustment_date,
        }

        return templates.TemplateResponse(
            "adjustment_receipt.html", 
            {"request": request, "adjustment_details": adjustment_details}
        )
    
    except Exception as e:
        connection.rollback()
    
    finally:
        cursor.close()
        connection.close()



if __name__ == "__main__":
    uvicorn.run(app, host='0.0.0.0', port=8000)


