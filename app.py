from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
import sqlite3
import csv
import io
from datetime import datetime, date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask import jsonify
import math

app = Flask(__name__)
import os
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "replace-this-with-a-long-random-secret-before-deploying"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "electricity.db")


def get_db_connection():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def create_table():
    connection = get_db_connection()

    # Create the users table (keeps your existing accounts)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            property_type TEXT NOT NULL,
            other_property TEXT
        )
    """)

    # Create the appliance usage table
    connection.execute("""
        CREATE TABLE IF NOT EXISTS appliances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            appliance_name TEXT NOT NULL,
            power_watts REAL NOT NULL,
            hours_per_day REAL NOT NULL,
            entry_date TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    # Store electricity bill details entered by each user
    connection.execute("""
        CREATE TABLE IF NOT EXISTS bill_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            billing_period TEXT NOT NULL,
            units REAL NOT NULL,
            energy_charges REAL NOT NULL,
            fixed_charges REAL NOT NULL,
            customer_charges REAL NOT NULL,
            electricity_duty REAL NOT NULL,
            fppca REAL NOT NULL,
            other_charges REAL NOT NULL,
            subsidy REAL NOT NULL,
            arrears REAL NOT NULL,
            total_amount REAL NOT NULL,
            average_rate REAL NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    # Save each user's average electricity rate
    connection.execute("""
        CREATE TABLE IF NOT EXISTS user_rates (
            user_id INTEGER PRIMARY KEY,
            rate_per_unit REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    connection.commit()
    connection.close()


create_table()

@app.route("/")
def home():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Electricity Usage Predictor</title>

        <style>
            body {
                font-family: Arial, sans-serif;
                background: #f3f7f5;
                margin: 0;
                padding: 40px 20px;
                color: #20332b;
                text-align: center;
            }

            .card {
                max-width: 650px;
                margin: 40px auto;
                padding: 35px;
                background: white;
                border-radius: 16px;
                box-shadow: 0 4px 18px rgba(0, 0, 0, 0.08);
            }

            h1 {
                color: #16794c;
            }

            p {
                line-height: 1.6;
            }

            .button {
                display: inline-block;
                margin: 12px 6px;
                padding: 12px 22px;
                background: #16794c;
                color: white;
                text-decoration: none;
                border-radius: 8px;
            }

            .button:hover {
                background: #105e3a;
            }
        </style>
    </head>

    <body>
        <div class="card">
            <h1>Electricity Usage Predictor</h1>

            <p>
                Understand your electricity usage, estimate your bill,
                and discover ways to save energy.
            </p>

            <p><strong>Your electricity, made easier to understand.</strong></p>

            <a class="button" href="/register">Create an Account</a>
            <a class="button" href="/login">Login</a>
        </div>
    </body>
    </html>
    """


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        property_type = request.form.get("property_type") or ""
        other_property = request.form.get("other_property", "").strip()

        if not name or not email or not password or not property_type:
            flash("Please fill in all required fields.")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash("Password must contain at least 8 characters.")
            return redirect(url_for("register"))

        if property_type == "Other" and not other_property:
            flash("Please specify your property type.")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)

        connection = get_db_connection()

        try:
            connection.execute("""
                INSERT INTO users
                (name, email, password, property_type, other_property)
                VALUES (?, ?, ?, ?, ?)
            """, (name, email, hashed_password, property_type, other_property))

            connection.commit()

        except sqlite3.IntegrityError:
            connection.close()
            flash("This email is already registered. Please log in.")
            return redirect(url_for("register"))

        connection.close()

        flash("Account created successfully. Please log in.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        if not email or not password:
            flash("Please enter both email and password.")
            return render_template("login.html")

        connection = get_db_connection()

        user = connection.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        connection.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))

        flash("Email or password is incorrect.")

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()

    # Find the latest date with appliance records for this user
    latest = connection.execute("""
        SELECT MAX(entry_date) AS latest_date
        FROM appliances
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    daily_kwh = 0
    has_usage = False

    if latest["latest_date"]:
        has_usage = True

        result = connection.execute("""
            SELECT COALESCE(
                SUM(power_watts * hours_per_day / 1000.0), 0
            ) AS total_kwh
            FROM appliances
            WHERE user_id = ? AND entry_date = ?
        """, (session["user_id"], latest["latest_date"])).fetchone()

        daily_kwh = round(result["total_kwh"], 3)

    # Load this user's saved rate whether or not usage exists
    saved_rate = connection.execute("""
        SELECT rate_per_unit
        FROM user_rates
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    rate_per_unit = saved_rate["rate_per_unit"] if saved_rate else None

    connection.close()

    monthly_kwh = round(daily_kwh * 30, 2)

    return render_template(
        "dashboard.html",
        user_name=session["user_name"],
        daily_kwh=daily_kwh,
        monthly_kwh=monthly_kwh,
        has_usage=has_usage,
        rate_per_unit=rate_per_unit
    )

@app.route("/save-electricity-rate", methods=["POST"])
def save_electricity_rate():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please log in again."}), 401

    data = request.get_json(silent=True) or {}
    rate = data.get("rate_per_unit")

    try:
        rate = float(rate)
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "message": "Please enter a valid rate."
        }), 400

    if rate < 0 or not math.isfinite(rate):
        return jsonify({
            "success": False,
            "message": "Rate must be a valid number of zero or more."
        }), 400

    connection = get_db_connection()

    connection.execute("""
        INSERT INTO user_rates (user_id, rate_per_unit)
        VALUES (?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET rate_per_unit = excluded.rate_per_unit
    """, (session["user_id"], rate))

    connection.commit()
    connection.close()

    return jsonify({"success": True, "message": "Electricity rate saved."})

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/usage", methods=["GET", "POST"])
def usage():
    if "user_id" not in session:
        return redirect(url_for("login"))

    message = None

    if request.method == "POST":
        appliance_name = (request.form.get("appliance_name") or "").strip()
        power_watts = request.form.get("power_watts", type=float)
        hours_per_day = request.form.get("hours_per_day", type=float)
        entry_date = request.form.get("entry_date") or ""

        # Check that the entered values are sensible
        if (
            not appliance_name
            or power_watts is None
            or hours_per_day is None
            or not entry_date
            or power_watts <= 0
            or hours_per_day < 0
            or hours_per_day > 24
        ):
            message = "Please enter a name, positive power rating, usage from 0 to 24 hours, and a valid date."
        else:
            connection = get_db_connection()

            connection.execute("""
                INSERT INTO appliances
                (user_id, appliance_name, power_watts, hours_per_day, entry_date)
                VALUES (?, ?, ?, ?, ?)
            """, (
                session["user_id"],
                appliance_name,
                power_watts,
                hours_per_day,
                entry_date
            ))

            connection.commit()
            connection.close()

            message = "Appliance usage saved successfully!"

    # Fetch only this logged-in user's records
    connection = get_db_connection()

    appliances = connection.execute("""
        SELECT appliance_name, power_watts, hours_per_day, entry_date
        FROM appliances
        WHERE user_id = ?
        ORDER BY entry_date DESC, id DESC
    """, (session["user_id"],)).fetchall()

    connection.close()

    # Calculate daily kWh for each saved appliance
    appliance_rows = []
    total_daily_kwh = 0

    for appliance in appliances:
        daily_kwh = (
            appliance["power_watts"] * appliance["hours_per_day"] / 1000
        )

        total_daily_kwh += daily_kwh

        appliance_rows.append({
            "name": appliance["appliance_name"],
            "watts": appliance["power_watts"],
            "hours": appliance["hours_per_day"],
            "date": appliance["entry_date"],
            "daily_kwh": round(daily_kwh, 3)
        })

    return render_template(
        "usage.html",
        user_name=session["user_name"],
        message=message,
        appliances=appliance_rows,
        total_daily_kwh=round(total_daily_kwh, 3)
    )
@app.route("/bill-estimator", methods=["GET", "POST"])
def bill_estimator():
    if "user_id" not in session:
        return redirect(url_for("login"))

    result = None
    error = None

    if request.method == "POST":
        method = request.form.get("method")

        if method == "known_bill":
            try:
                units = float(request.form.get("units", 0))
                amount = float(request.form.get("amount", 0))

                if units <= 0 or amount < 0:
                    error = "Enter units greater than 0 and a bill amount of 0 or more."
                else:
                    average_rate = amount / units
                    result = {
                        "units": units,
                        "amount": amount,
                        "rate": average_rate,
                        "estimated_bill": average_rate * units,
                    }

            except ValueError:
                error = "Please enter valid numbers for units and bill amount."

        elif method == "guided":
            state = request.form.get("state")
            discom = request.form.get("discom")
            connection_type = request.form.get("connection_type")

            try:
                monthly_units = float(request.form.get("monthly_units", 0))

                if monthly_units <= 0:
                    error = "Enter monthly units greater than 0."

                elif state != "Andhra Pradesh" or discom != "APCPDCL":
                    error = "This guided calculator is currently being prepared for APCPDCL, Andhra Pradesh."

                elif connection_type != "Home":
                    error = "For now, the guided calculator is being prepared for Home / Residential connections."

                else:
                    error = (
                        f"You entered {monthly_units:.2f} kWh for an APCPDCL "
                        "residential connection. The verified tariff slab calculation "
                        "is the next step; no bill amount has been guessed."
                    )

            except ValueError:
                error = "Please enter valid monthly units."

    return render_template(
        "bill_estimator.html",
        result=result,
        error=error
    )

@app.route("/enter-bill-charges", methods=["GET", "POST"])
def enter_bill_charges():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        billing_period = request.form.get("billing_period", "")
        units = float(request.form.get("units", 0) or 0)

        energy = float(request.form.get("energy_charges", 0) or 0)
        fixed = float(request.form.get("fixed_charges", 0) or 0)
        customer = float(request.form.get("customer_charges", 0) or 0)
        duty = float(request.form.get("electricity_duty", 0) or 0)
        fppca = float(request.form.get("fppca", 0) or 0)
        other = float(request.form.get("other_charges", 0) or 0)
        subsidy = float(request.form.get("subsidy", 0) or 0)
        arrears = float(request.form.get("arrears", 0) or 0)

        # Charges are added; subsidy is deducted.
        total = (
            energy + fixed + customer + duty
            + fppca + other + arrears - subsidy
        )

        average_rate = total / units if units > 0 else 0

        connection = get_db_connection()

        connection.execute("""
            INSERT INTO bill_records (
                user_id, billing_period, units,
                energy_charges, fixed_charges, customer_charges,
                electricity_duty, fppca, other_charges,
                subsidy, arrears, total_amount, average_rate
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session["user_id"],
            billing_period,
            units,
            energy,
            fixed,
            customer,
            duty,
            fppca,
            other,
            subsidy,
            arrears,
            total,
            average_rate
        ))
      
        connection.commit()
        connection.close()

        return render_template(
            "bill_charges_result.html",
            billing_period=billing_period,
            units=units,
            energy=energy,
            fixed=fixed,
            customer=customer,
            duty=duty,
            fppca=fppca,
            other=other,
            subsidy=subsidy,
            arrears=arrears,
            total=total,
            average_rate=average_rate
        )

    return render_template("enter_bill_charges.html")

@app.route("/bill-history")
def bill_history():
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()

    bills = connection.execute("""
        SELECT
            id,
            billing_period,
            units,
            energy_charges,
            fixed_charges,
            customer_charges,
            electricity_duty,
            fppca,
            other_charges,
            subsidy,
            arrears,
            total_amount,
            average_rate,
            created_at
        FROM bill_records
        WHERE user_id = ?
        ORDER BY id DESC
    """, (session["user_id"],)).fetchall()

    connection.close()

    return render_template(
        "bill_history.html",
        bills=bills
    )

@app.route("/history")
def history():
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()

    records = connection.execute("""
        SELECT
            id,
            appliance_name,
            power_watts,
            hours_per_day,
            entry_date,
            power_watts * hours_per_day / 1000.0 AS daily_kwh
        FROM appliances
        WHERE user_id = ?
        ORDER BY entry_date DESC, id DESC
    """, (session["user_id"],)).fetchall()

    # Calculate the combined appliance energy for each date
    daily_totals = connection.execute("""
        SELECT
            entry_date,
            SUM(power_watts * hours_per_day / 1000.0) AS total_kwh
        FROM appliances
        WHERE user_id = ?
        GROUP BY entry_date
        ORDER BY entry_date DESC
    """, (session["user_id"],)).fetchall()

    connection.close()

    return render_template(
        "history.html",
        records=records,
        daily_totals=daily_totals,
        user_name=session["user_name"]
    )

@app.route("/delete-usage/<int:record_id>", methods=["POST"])
def delete_usage(record_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()

    # Delete only a record belonging to the logged-in user
    connection.execute("""
        DELETE FROM appliances
        WHERE id = ? AND user_id = ?
    """, (record_id, session["user_id"]))

    connection.commit()
    connection.close()

    flash("Usage record deleted.")
    return redirect(url_for("history"))

@app.route("/weekly-usage-data")
def weekly_usage_data():
    if "user_id" not in session:
        return {"error": "Please log in"}, 401

    from datetime import date, timedelta

    today = date.today()
    first_day = today - timedelta(days=6)

    connection = get_db_connection()

    rows = connection.execute(
        """
        SELECT
            entry_date,
            SUM(power_watts * hours_per_day / 1000.0) AS total_kwh
        FROM appliances
        WHERE user_id = ?
          AND entry_date >= ?
          AND entry_date <= ?
        GROUP BY entry_date
        """,
        (session["user_id"], first_day.isoformat(), today.isoformat())
    ).fetchall()

    connection.close()

    # Convert database results into a date-to-consumption dictionary
    usage_by_date = {
        row["entry_date"]: round(row["total_kwh"], 3)
        for row in rows
    }

    # Create labels and values for all 7 days
    labels = []
    values = []

    for day_number in range(7):
        current_day = first_day + timedelta(days=day_number)
        day_label = current_day.isoformat()

        labels.append(day_label)
        values.append(usage_by_date.get(day_label, 0))

    return {
        "labels": labels,
        "values": values
    }

@app.route("/forecast-data")
def forecast_data():
    if "user_id" not in session:
        return {"error": "Please log in"}, 401

    from datetime import date, timedelta
    from sklearn.linear_model import LinearRegression

    connection = get_db_connection()

    rows = connection.execute(
        """
        SELECT
            entry_date,
            SUM(power_watts * hours_per_day / 1000.0) AS total_kwh
        FROM appliances
        WHERE user_id = ?
        GROUP BY entry_date
        ORDER BY entry_date
        """,
        (session["user_id"],)
    ).fetchall()

    connection.close()

    # Need at least 3 different dated records to train a simple model
    if len(rows) < 3:
        return {
            "message": "Add usage records for at least 3 different dates to create a forecast."
        }

    dates = [date.fromisoformat(row["entry_date"]) for row in rows]
    usage_values = [float(row["total_kwh"]) for row in rows]

    # Convert dates to numbers for Linear Regression
    first_date = dates[0]
    x_values = [[(day - first_date).days] for day in dates]

    model = LinearRegression()
    model.fit(x_values, usage_values)

    # Predict consumption for the next 7 days
    today = date.today()
    forecast_dates = []
    forecast_values = []

    for day_number in range(1, 8):
        future_date = today + timedelta(days=day_number)
        date_number = (future_date - first_date).days

        predicted_kwh = model.predict([[date_number]])[0]

        # Electricity consumption cannot be negative
        predicted_kwh = max(0, predicted_kwh)

        forecast_dates.append(future_date.isoformat())
        forecast_values.append(round(predicted_kwh, 3))

    estimated_30_day_kwh = round(sum(forecast_values) / 7 * 30, 3)

    return {
        "forecast_dates": forecast_dates,
        "forecast_kwh": forecast_values,
        "estimated_30_day_kwh": estimated_30_day_kwh
    }

@app.route("/appliance-analysis-data")
def appliance_analysis_data():
    if "user_id" not in session:
        return {"error": "Please log in"}, 401

    connection = get_db_connection()

    # Find the most recent date on which this user entered usage
    latest = connection.execute(
        """
        SELECT MAX(entry_date) AS latest_date
        FROM appliances
        WHERE user_id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    latest_date = latest["latest_date"]

    if not latest_date:
        connection.close()
        return {
            "date": None,
            "appliances": [],
            "message": "Enter appliance usage to see the analysis."
        }

    rows = connection.execute(
        """
        SELECT
            appliance_name,
            SUM(power_watts * hours_per_day / 1000.0) AS daily_kwh
        FROM appliances
        WHERE user_id = ?
          AND entry_date = ?
        GROUP BY appliance_name
        ORDER BY daily_kwh DESC
        """,
        (session["user_id"], latest_date)
    ).fetchall()

    connection.close()

    total_kwh = sum(float(row["daily_kwh"]) for row in rows)

    appliance_list = []

    for row in rows:
        kwh = float(row["daily_kwh"])

        percentage = (kwh / total_kwh * 100) if total_kwh > 0 else 0

        appliance_list.append({
            "name": row["appliance_name"],
            "kwh": round(kwh, 3),
            "percentage": round(percentage, 1)
        })

    return {
        "date": latest_date,
        "total_kwh": round(total_kwh, 3),
        "appliances": appliance_list
    }

@app.route("/download-usage-report")
def download_usage_report():
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()

    rows = connection.execute(
        """
        SELECT entry_date, appliance_name, power_watts, hours_per_day,
               (power_watts * hours_per_day / 1000.0) AS daily_kwh
        FROM appliances
        WHERE user_id = ?
        ORDER BY entry_date DESC
        """,
        (session["user_id"],)
    ).fetchall()

    connection.close()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Date",
        "Appliance",
        "Power (W)",
        "Hours per day",
        "Estimated energy (kWh/day)"
    ])

    for row in rows:
        writer.writerow([
            row["entry_date"],
            row["appliance_name"],
            row["power_watts"],
            row["hours_per_day"],
            round(row["daily_kwh"], 3)
        ])

    csv_data = "\ufeff" + output.getvalue()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition":
                "attachment; filename=electricity_usage_report.csv"
        }
    )

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        uploaded_file = request.files.get("csv_file")

        if not uploaded_file or uploaded_file.filename == "":
            flash("Please choose a CSV file.")
            return redirect(url_for("upload"))

        if not uploaded_file.filename.lower().endswith(".csv"):
            flash("Please upload a .csv file.")
            return redirect(url_for("upload"))

        try:
            content = uploaded_file.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(content))

            if not reader.fieldnames:
                flash("The CSV file is empty or has no headings.")
                return redirect(url_for("upload"))

            # Normalize column headings, including common Excel headings.
            heading_map = {
                heading.strip().lower(): heading
                for heading in reader.fieldnames
            }

            date_heading = heading_map.get("date")
            appliance_heading = heading_map.get("appliance")
            power_heading = (
                heading_map.get("power_watts")
                or heading_map.get("power (w)")
            )
            hours_heading = (
                heading_map.get("hours_per_day")
                or heading_map.get("hours per day")
                or heading_map.get("hours/day")
            )

            if not all([
                date_heading,
                appliance_heading,
                power_heading,
                hours_heading
            ]):
                flash(
                    "CSV must contain these columns: Date, Appliance, "
                    "Power (W), Hours per day."
                )
                return redirect(url_for("upload"))

            connection = get_db_connection()
            imported_count = 0

            try:
                for row in reader:
                    try:
                        entry_date = datetime.strptime(
                            row[date_heading].strip(), "%Y-%m-%d"
                        ).date().isoformat()

                        appliance_name = row[appliance_heading].strip()
                        power_watts = float(row[power_heading])
                        hours_per_day = float(row[hours_heading])

                        if (
                            not appliance_name
                            or power_watts <= 0
                            or hours_per_day < 0
                            or hours_per_day > 24
                        ):
                            continue

                        # Check whether the same usage record already exists
                        existing_record = connection.execute(
                            """
                            SELECT id
                            FROM appliances
                            WHERE user_id = ?
                            AND appliance_name = ?
                            AND power_watts = ?
                            AND hours_per_day = ?
                            AND entry_date = ?
                            LIMIT 1
                            """,
                            (
                                session["user_id"],
                                appliance_name,
                                power_watts,
                                hours_per_day,
                                entry_date
                            )
                        ).fetchone()

                        # Skip duplicate records
                        if existing_record:
                            continue

                        # Insert only new usage records
                        connection.execute(
                            """
                            INSERT INTO appliances
                                (user_id, appliance_name, power_watts,
                                hours_per_day, entry_date)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                session["user_id"],
                                appliance_name,
                                power_watts,
                                hours_per_day,
                                entry_date
                            )
                        )

                        imported_count += 1

                    except (ValueError, KeyError, TypeError):
                        # Skip rows that have invalid or missing values.
                        continue

                connection.commit()

            finally:
                connection.close()

            flash(f"Imported {imported_count} usage record(s).")
            return redirect(url_for("history"))

        except Exception as error:
            print("CSV upload error:", error)
            flash("Could not import the file. Please check its format.")
            return redirect(url_for("upload"))

    return render_template("upload.html")

if __name__ == "__main__":
    app.run(debug=False)