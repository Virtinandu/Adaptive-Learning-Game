# create the app, handle requests, send JSON, and show HTML pages.
from flask import Flask, request, jsonify, render_template
# make password secure
from flask_bcrypt import Bcrypt
# allow connections from CORS
from flask_cors import CORS
# connect with your database.
import mysql.connector
#To load and save machine learning models.
import pickle
#For handling data tables (CSV, DataFrames).
import pandas as pd
#To check if model exists
import os
#runs external Python files .
import subprocess

#Create the Flask app and set the folder for HTML templates.
app1 = Flask(__name__, template_folder='login/templates')

#Enable password encryption for the app.
bcrypt = Bcrypt(app1)

#Allow web apps to connect to this app.
CORS(app1)

# MySQL DB Connection Helper 
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="adaptive"
    )

#Show the profile page with the user's highest score.
@app1.route('/profile/<username>')
def profile(username):
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("SELECT MAX(score) FROM scores WHERE username = %s", (username,))
        result = cursor.fetchone()
        high_score = result[0] if result[0] is not None else "No scores yet"
        cursor.close()
        db.close()

        # Get performance insights
        insights_response = get_performance_insights(username)
        insights_data = insights_response.get_json()
        insights = insights_data.get("insights", []) if "insights" in insights_data else ["No insights available"]

        return render_template('profile.html', username=username, high_score=high_score, insights=insights)
    except Exception as e:
        return render_template('profile.html', username=username, high_score="Error loading score", insights=["Error fetching insights"])


#Adds a new user to the database after encrypting their password.
@app1.route('/signup', methods=['POST'])
def signup():
    data = request.json
    full_name = data.get('full_name')
    username = data.get('username')
    password = data.get('password')

    if not all([full_name, username, password]):
        return jsonify({"error": "Missing required fields"}), 400

    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("INSERT INTO users (full_name, username, password_hash) VALUES (%s, %s, %s)",
                       (full_name, username, hashed_password))
        db.commit()
        cursor.close()
        db.close()
        return jsonify({"message": "User registered successfully!"}), 200
    except mysql.connector.Error as err:
        print("Signup Error:", err)
        return jsonify({"error": "Username already exists or DB error"}), 400

#Checks if the entered username and password match a registered user.
@app1.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not all([username, password]):
        return jsonify({"error": "Missing username or password"}), 400

    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()
    cursor.close()
    db.close()

    if user and bcrypt.check_password_hash(user[0], password):
        return jsonify({"message": "Login successful!"}), 200
    else:
        return jsonify({"error": "Invalid credentials"}), 401

#Saves user's score in DB and retrains the ML model. Updates if old score exists.
@app1.route('/submit_score', methods=['POST'])
def submit_score():
    data = request.json
    username = data.get('username')
    subject = data.get('subject')
    quiz_topic = data.get('quiz_topic')
    score = data.get('score')
    total_questions = data.get('total_questions')

    if None in([username, subject, quiz_topic, score, total_questions]):
        return jsonify({"error": "Missing data"}), 400

    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("""
            SELECT score FROM scores WHERE username = %s AND subject = %s AND quiz_topic = %s
        """, (username, subject, quiz_topic))
        existing_score = cursor.fetchone()

        if existing_score:
            cursor.execute("""
                UPDATE scores SET score = %s, total_questions = %s, date = NOW()
                WHERE username = %s AND subject = %s AND quiz_topic = %s
            """, (score, total_questions, username, subject, quiz_topic))
        else:
            cursor.execute("""
                INSERT INTO scores (username, subject, quiz_topic, score, total_questions, date)
                VALUES (%s, %s, %s, %s, %s, NOW())
            """, (username, subject, quiz_topic, score, total_questions))
        db.commit()
        cursor.close()
        db.close()

        # Optional: retrain model only if needed
        subprocess.call(['python', 'model/train_model.py'])

        return jsonify({"message": "Score processed and model retrained!"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

#Fetches all subject scores of the user.
@app1.route('/get_scores/<username>', methods=['GET'])
def get_scores(username):
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("""
            SELECT subject, score
            FROM scores WHERE username = %s
        """, (username,))
        scores_data = cursor.fetchall()
        cursor.close()
        db.close()

        if not scores_data:
            return jsonify({"error": "No scores found for the user"}), 404

        response_data = [
            {"subject": entry[0], "score": entry[1]}
            for entry in scores_data
        ]

        return jsonify(response_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

#a URL to get a user's weak subjects.
@app1.route('/get_weak_subjects/<username>', methods=['GET'])
def get_weak_subjects(username):
    #Starts error-catching, so if something breaks, it won’t crash.
    try:
        #Sets the file paths for the model and feature names.
        model_path = 'model/ml_model.pkl'
        feature_columns_path = 'model/feature_columns.pkl'

        #Checks if those files actually exist. If not, it returns an error.
        if not os.path.exists(model_path) or not os.path.exists(feature_columns_path):
            return jsonify({"error": "Model or feature columns file not found"}), 500

        #Opens the model and feature files.
        with open(model_path, 'rb') as f:
            model = pickle.load(f)
        with open(feature_columns_path, 'rb') as f:
            feature_columns = pickle.load(f)

        #Loads the model and the list of features.
        df = pd.read_csv("model/user_subjects.csv")

        #Filters the data to get only the current user's info.
        user_df = df[df['username'] == username]

        #If no data is found for that user, it returns a message.
        if user_df.empty:
            return jsonify({"message": "No performance data available for user."}), 200

        #Picks only the relevant columns for prediction
        X = user_df[feature_columns]

        #Uses the model to predict which subjects are weak.
        preds = model.predict(X)

        #Selects subjects where prediction = weak (1).
        weak_subjects = user_df[preds == 1]['subject'].tolist()

        #Sends the result back as a JSON response.
        return jsonify({"username": username, "weak_subjects": weak_subjects}), 200
    
    #If anything breaks, it goes here and sends the error message.
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

#a URL to get user"s strong subjects.
@app1.route('/get_strong_subjects/<username>', methods=['GET'])
def get_strong_subjects(username):
    try:
        model_path = 'model/ml_model.pkl'
        feature_columns_path = 'model/feature_columns.pkl'

        if not os.path.exists(model_path) or not os.path.exists(feature_columns_path):
            return jsonify({"error": "Model or feature columns file not found"}), 500

        with open(model_path, 'rb') as f:
            model = pickle.load(f)
        with open(feature_columns_path, 'rb') as f:
            feature_columns = pickle.load(f)

        df = pd.read_csv("model/user_subjects.csv")
        user_df = df[df['username'] == username]

        if user_df.empty:
            return jsonify({"message": "No performance data available for user."}), 200

        X = user_df[feature_columns]
        preds = model.predict(X)

        # Assuming '0' means strong subject (opposite of weak = 1)
        strong_subjects = user_df[preds == 0]['subject'].tolist()
        return jsonify({"username": username, "strong_subjects": strong_subjects}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

#URL to get personalized performance
@app1.route('/get_performance_insights/<username>', methods=['GET'])
def get_performance_insights(username):
    try:
        model_path = 'model/ml_model.pkl'
        feature_columns_path = 'model/feature_columns.pkl'

        if not os.path.exists(model_path) or not os.path.exists(feature_columns_path):
            return jsonify({"error": "Model or feature columns file not found"}), 500

        with open(model_path, 'rb') as f:
            model = pickle.load(f)
        with open(feature_columns_path, 'rb') as f:
            feature_columns = pickle.load(f)

        df = pd.read_csv("model/user_subjects.csv")
        user_df = df[df['username'] == username]

        if user_df.empty:
            return jsonify({"message": "No performance data available for user."}), 200

        X = user_df[feature_columns]
        preds = model.predict(X)
        weak_subjects = user_df[preds == 1]['subject'].tolist()

        insights = []
        if len(weak_subjects) == 0:
            insights.append("Great job! No weak subjects detected.")
        else:
            insights.append(f"You have {len(weak_subjects)} weak subjects: {', '.join(weak_subjects)}.")
            insights.append("Consider focusing more on these subjects for improvement.")

        return jsonify({"username": username, "insights": insights}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app1.route('/get_model_predictions/<username>')
def get_model_predictions(username):
    df = pd.read_csv('model/user_subjects.csv')
    user_df = df[df['username'] == username]
    return jsonify(user_df.to_dict(orient='records'))

if __name__ == '__main__':
    app1.run(debug=True)
