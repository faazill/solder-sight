                st.markdown('<div class="section-title">Selected joint</div>', unsafe_allow_html=True)
                st.image(crop, caption="This close-up will be sent for assessment.", use_container_width=True)
            with details_col:
                st.markdown('<div class="section-title">Region details</div>', unsafe_allow_html=True)
                st.write(f"**Joint:** {selected_joint['joint_id']}")
                st.write(f"**Visibility estimate:** {selected_joint.get('visibility','not specified').replace('_',' ').title()}")
                st.write(f"**Region:** {selected_joint.get('description','Candidate solder region')}")
                inspect_btn = st.button("Inspect this joint", type="primary", use_container_width=True)
                if inspect_btn:
                    with st.spinner("Assessing visible solder quality…"):
                        try:
                            report, verifier = run_inspection(client, model_name, crop, enhanced_review)
                            st.session_state["inspection"] = report
                            st.session_state["verifier"] = verifier
                            st.session_state["report"] = {
                                "application": APP_NAME,
                                "image_filename": uploaded.name,
                                "inspected_at_utc": datetime.now(timezone.utc).isoformat(),
                                "joint_id": selected_joint["joint_id"],
                                "assessment": report,
                                "second_review": verifier,
                            }
                        except Exception as exc:
                            st.error(f"Inspection failed: {str(exc)[:600]}")
        else:
            st.warning("No candidate joints were returned. You can manually choose a crop below.")

        with st.expander("Manual crop selection", expanded=not bool(joints)):
            st.caption("Use this when the automatic boxes miss the joint. Adjust the rectangle in image-pixel coordinates.")
            a,b,c,d = st.columns(4)
            x = a.number_input("Left (px)", min_value=0, max_value=max(0,image.width-1), value=0, step=max(1,image.width//20))
            y = b.number_input("Top (px)", min_value=0, max_value=max(0,image.height-1), value=0, step=max(1,image.height//20))
            cw = c.number_input("Width (px)", min_value=1, max_value=image.width, value=max(1,image.width//4), step=max(1,image.width//20))
            ch = d.number_input("Height (px)", min_value=1, max_value=image.height, value=max(1,image.height//4), step=max(1,image.height//20))
            mx,my = min(image.width,int(x+cw)), min(image.height,int(y+ch))
            manual_crop = image.crop((int(x),int(y),mx,my))
            st.image(manual_crop, caption="Manual crop preview", width=520)
            if st.button("Inspect manual crop", key="manual_inspect", type="secondary"):
                with st.spinner("Assessing selected crop…"):
                    try:
                        report, verifier = run_inspection(client, model_name, manual_crop, enhanced_review)
                        st.session_state["inspection"] = report
                        st.session_state["verifier"] = verifier
                        st.session_state["report"] = {
                            "application": APP_NAME,
                            "image_filename": uploaded.name,
                            "inspected_at_utc": datetime.now(timezone.utc).isoformat(),
                            "joint_id": "manual crop",
                            "assessment": report,
                            "second_review": verifier,
                        }
                    except Exception as exc:
                        st.error(f"Inspection failed: {str(exc)[:600]}")

    report = st.session_state.get("inspection")
    if report:
        st.markdown("---")
        st.markdown('<div class="section-title">Inspection report</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-help">Review the visual evidence and recommended action before making a quality decision.</div>', unsafe_allow_html=True)
        status_banner(report.get("recommendation","inspect_further"))
        m1,m2,m3 = st.columns(3)
        m1.metric("Visual assessment", report.get("quality","uncertain").replace("_"," ").title())
        m2.metric("Joint status", report.get("joint_status","unclear").replace("_"," ").title())
        m3.metric("Confidence", report.get("confidence","low").title())
        st.markdown("#### Description")
        st.write(report.get("description","No description provided."))
        defects = report.get("defects",[])
        st.markdown("#### Visible findings")
        if defects:
            for defect in defects:
                if isinstance(defect,dict):
                    severity = defect.get("severity","unspecified").title()
                    st.markdown(f"**{defect.get('name','Finding')}** · {severity}")
                    st.write(defect.get("evidence",""))
                else:
                    st.write(f"- {defect}")
        else:
            st.write("No specific visible defect was reported. This is not proof that the joint is defect-free.")
        st.markdown("#### Why this action was recommended")
        st.write(report.get("reason",""))
        iq = report.get("image_quality",{})
        if iq:
            with st.expander("Image quality and limitations"):
                st.write(f"**Focus:** {iq.get('focus','not assessed').title()}")
                st.write(f"**Lighting:** {iq.get('lighting','not assessed').title()}")
                st.write(f"**Occlusion:** {iq.get('occlusion','not assessed').title()}")
                for item in report.get("limitations",[]):
                    st.write(f"- {item}")
        verifier = st.session_state.get("verifier")
        if enhanced_review and verifier:
            with st.expander("Consistency review"):
                st.write("**Agreement:**", verifier.get("agreement","unavailable").replace("_"," ").title())
                st.write(verifier.get("review_note",""))
                concerns = verifier.get("missed_concerns",[])
                if concerns:
                    st.write("**Additional concerns:**")
                    for concern in concerns:
                        st.write(f"- {concern}")
        st.download_button(
            "Download inspection report (JSON)",
            data=json.dumps(st.session_state.get("report",report),indent=2,ensure_ascii=False),
            file_name="soldersight_inspection_report.json",
            mime="application/json",
            type="primary",
        )
        st.caption(
            "Important: this is image-based decision support. Verify critical joints using appropriate inspection methods. "
            "Visual analysis cannot confirm electrical continuity or hidden defects."
        )
else:
    st.markdown("---")
    c1,c2,c3 = st.columns(3)
    with c1:
        st.markdown("#### 1. Upload")
        st.write("Start with a clear photo of a PCB or soldered area.")
    with c2:
        st.markdown("#### 2. Select")
        st.write("Review candidate regions and choose the joint you want assessed.")
    with c3:
        st.markdown("#### 3. Inspect")
        st.write("Get an evidence-based description and a conservative recommended action.")
    st.info("For the most useful assessment, upload a close-up of a completed solder joint with the neighboring pads visible.")
