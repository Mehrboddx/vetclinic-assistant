import streamlit as st


pg = st.navigation([
    st.Page("pages/landing.py", title="Guide", default = True),
    st.Page("pages/submit.py", title="Submit"),
    st.Page("pages/search.py", title="Search",),
])
pg.run()