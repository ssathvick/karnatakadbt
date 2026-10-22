package org.karnatakadbt.migration;

import org.springframework.boot.SpringApplication;

/** The original main calls SpringApplication.run with its one application class.
 * Add the approved recovery security configuration to that same application.
 * No business classes, authentication checks or original JAR bytes are changed.
 */
public class NativePortalBootstrap {
    public static void main(String[] args) throws ClassNotFoundException {
        Class<?> original=Class.forName("io.mosip.certify.CertifyServiceApplication");
        SpringApplication.run(new Class<?>[]{original,NativePortalAuthorityConfiguration.class},args);
    }
}
