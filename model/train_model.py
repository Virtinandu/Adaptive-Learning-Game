import pandas as pd
import mysql.connector
import pickle
from sklearn.tree import DecisionTreeClassifier

# Connect to MySQL
conn = mysql.connector.connect(
    host='localhost',
    user='root',
    password='',
    database='adaptive'
)
cursor = conn.cursor()

# Fetch data
query = "SELECT username, subject, score, total_questions FROM scores"
cursor.execute(query)
rows = cursor.fetchall()
df = pd.DataFrame(rows, columns=['username', 'subject', 'score', 'total_questions'])

# Calculate percentage
df['percentage'] = df['score'] / df['total_questions'] * 100

# Quiz count per (username, subject)
quiz_counts = df.groupby(['username', 'subject']).size().reset_index(name='quiz_count')
df = pd.merge(df, quiz_counts, on=['username', 'subject'], how='left')

# Label weak subjects: 1 = weak, 0 = strong
df['is_weak'] = df['percentage'].apply(lambda x: 1 if x < 50 else 0)

# Prepare data for training
X = df[['percentage', 'quiz_count']]
y = df['is_weak']

# Creates a new Decision Tree model object and Trains the model using the feature set (X) and labels (y).
model = DecisionTreeClassifier()
model.fit(X, y)

# Saves the trained model to a file called ml_model.pkl 
with open('model/ml_model.pkl', 'wb') as f:
    pickle.dump(model, f)
#Saves the names of the features used in training
with open('model/feature_columns.pkl', 'wb') as f:
    pickle.dump(['percentage', 'quiz_count'], f)

#Saves user + subject data + model labels to a CSV file. Useful for analysis.
df[['username', 'subject', 'percentage', 'quiz_count', 'is_weak']].to_csv('model/user_subjects.csv', index=False)

print("[✅] ML Model trained and saved.")
