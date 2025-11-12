import streamlit as st

st.title("G検定クイズアプリ（テスト版）")

question = "人工知能の三つの要素に含まれないものはどれ？"
options = ["学習", "推論", "記憶", "知覚"]

answer = st.radio("選択肢を選んでください", options)

if st.button("回答する"):
    if answer == "記憶":
        st.success("正解！🎉『記憶』はAIの三要素ではありません。")
    else:
        st.error("不正解です。AIの三要素は『学習』『推論』『知覚』です。")
