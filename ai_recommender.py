
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def recommend_hostels(hostels, preferences):
    """
    Recommend hostels using TF-IDF and cosine similarity.

    Budget is treated as a strict maximum.
    Other preferences are used to rank matching hostels.
    """

    if not hostels:
        return []

    # Extract student preferences
    locality = preferences.get("locality", "").strip()
    room_type = preferences.get("room_type", "").strip()
    gender_policy = preferences.get("gender_policy", "").strip()
    facilities = preferences.get("facilities", "").strip()
    college = preferences.get("college", "").strip()

    # Build the student's preference text
    preference_text = " ".join([
        locality,
        room_type,
        gender_policy,
        facilities,
        college
    ]).strip()

    if not preference_text:
        return []

    # Create searchable text for each hostel
    hostel_documents = []

    for hostel in hostels:
        document = " ".join([
            str(hostel.name or ""),
            str(hostel.locality or ""),
            str(hostel.room_type or ""),
            str(hostel.gender_policy or ""),
            str(hostel.facilities or ""),
            str(hostel.college or ""),
            str(hostel.description or "")
        ])

        hostel_documents.append(document)

    try:
        # Convert hostel descriptions into TF-IDF vectors
        vectorizer = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2)
        )

        hostel_vectors = vectorizer.fit_transform(hostel_documents)

        # Convert student preferences into a vector
        preference_vector = vectorizer.transform([preference_text])

        # Calculate cosine similarity
        similarity_scores = cosine_similarity(
            preference_vector,
            hostel_vectors
        ).flatten()

    except ValueError:
        # Handles cases where hostel descriptions contain no useful text
        return []

    recommendations = []

    for hostel, score in zip(hostels, similarity_scores):
        recommendations.append({
            "hostel": hostel,
            "match_score": round(float(score) * 100, 2)
        })

    # Highest similarity first
    recommendations.sort(
        key=lambda item: item["match_score"],
        reverse=True
    )

    return recommendations
